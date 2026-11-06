using System.Net;
using System.Net.Http;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 4)
                throw new ArgumentException("Usage: Task071WpfPreview source.png smart.svg contour.svg output-directory");
            RunAsync(args).GetAwaiter().GetResult();
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static async Task RunAsync(string[] args)
    {
        var source = Path.GetFullPath(args[0]);
        var smartPath = Path.GetFullPath(args[1]);
        var contourPath = Path.GetFullPath(args[2]);
        var output = Path.GetFullPath(args[3]);
        Directory.CreateDirectory(output);
        var smartBytes = await File.ReadAllBytesAsync(smartPath);
        var contourBytes = await File.ReadAllBytesAsync(contourPath);
        var picker = new SmokePicker(source);
        var handler = new SvgResponseHandler(smartBytes, contourBytes);
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1/")
        };
        var api = new MediaStudioApiClient(http);
        var health = await api.GetHealthAsync();
        if (!health.ContourReady) throw new InvalidOperationException("Fake API capability response did not enable Contour.");

        var vm = new VectorizeToolViewModel(picker, api, health);
        vm.OpenImageCommand.Execute(null);
        if (!vm.HasImportedImage) throw new InvalidOperationException("Source did not load in VectorizeToolViewModel.");
        await vm.CompareCommand.ExecuteAsync();
        if (!vm.SmartHasResult || !vm.ContourHasResult)
            throw new InvalidOperationException($"Compare failed: smart={vm.SmartStateText}; contour={vm.ContourStateText}");
        if (vm.SmartPreviewImage is null || vm.ContourPreviewImage is null)
            throw new InvalidOperationException("Svg.Skia did not produce both ViewModel previews.");
        string[] handlerRequestOrder = handler.RequestOrder.ToArray();
        if (!handlerRequestOrder.SequenceEqual(new[] { "smart_reconstruction", "contour_preserving" }))
            throw new InvalidOperationException("ViewModel did not request Smart then Contour in Compare mode.");

        SaveBitmap(vm.SmartPreviewImage, Path.Combine(output, "smart_wpf_viewmodel_preview.png"));
        SaveBitmap(vm.ContourPreviewImage, Path.Combine(output, "contour_wpf_viewmodel_preview.png"));
        picker.EnqueueSave(Path.Combine(output, "smart_saved_from_wpf.svg"));
        picker.EnqueueSave(Path.Combine(output, "contour_saved_from_wpf.svg"));
        await vm.SaveBothCommand.ExecuteAsync();

        var smartSaved = await File.ReadAllBytesAsync(Path.Combine(output, "smart_saved_from_wpf.svg"));
        var contourSaved = await File.ReadAllBytesAsync(Path.Combine(output, "contour_saved_from_wpf.svg"));
        var report = new
        {
            status = "PASS",
            integrationKind = "VectorizeToolViewModel + VectorizationJobService + MediaStudioApiClient using deterministic HTTP response fixture containing the actual direct API SVG bytes; not a live backend or manual UI session",
            sourcePath = source,
            sourceSha256 = HashFile(source),
            requestedOrder = handlerRequestOrder,
            assetIdShared = true,
            smart = new
            {
                jobId = "task071-smart",
                method = "smart_reconstruction",
                inputSvgSha256 = Hash(smartBytes),
                inputSvgBytes = smartBytes.Length,
                previewWidth = vm.SmartPreviewImage.PixelWidth,
                previewHeight = vm.SmartPreviewImage.PixelHeight,
                previewPath = Path.Combine(output, "smart_wpf_viewmodel_preview.png"),
                previewSha256 = HashFile(Path.Combine(output, "smart_wpf_viewmodel_preview.png")),
                savedPath = Path.Combine(output, "smart_saved_from_wpf.svg"),
                savedSvgSha256 = Hash(smartSaved),
                savedByteCount = smartSaved.Length,
                exactSavedBytes = smartBytes.SequenceEqual(smartSaved)
            },
            contour = new
            {
                jobId = "task071-contour",
                method = "contour_preserving",
                inputSvgSha256 = Hash(contourBytes),
                inputSvgBytes = contourBytes.Length,
                previewWidth = vm.ContourPreviewImage.PixelWidth,
                previewHeight = vm.ContourPreviewImage.PixelHeight,
                previewPath = Path.Combine(output, "contour_wpf_viewmodel_preview.png"),
                previewSha256 = HashFile(Path.Combine(output, "contour_wpf_viewmodel_preview.png")),
                savedPath = Path.Combine(output, "contour_saved_from_wpf.svg"),
                savedSvgSha256 = Hash(contourSaved),
                savedByteCount = contourSaved.Length,
                exactSavedBytes = contourBytes.SequenceEqual(contourSaved)
            },
            manualWpfWindowQa = "not_tested",
            note = "Preview PNGs are rendered from the production ViewModel's Svg.Skia preview method; they are not screenshots of the running WPF window."
        };
        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
        await File.WriteAllTextAsync(Path.Combine(output, "wpf_routing_validation.json"), json, Encoding.UTF8);
        Console.WriteLine(json);

        if (!smartBytes.SequenceEqual(smartSaved) || !contourBytes.SequenceEqual(contourSaved))
            throw new InvalidOperationException("A WPF save changed the direct API SVG bytes.");
    }

    private static void SaveBitmap(BitmapSource bitmap, string path)
    {
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var output = File.Create(path);
        encoder.Save(output);
    }

    private static string Hash(byte[] value) => Convert.ToHexString(SHA256.HashData(value)).ToLowerInvariant();
    private static string HashFile(string path) => Hash(File.ReadAllBytes(path));

    private sealed class SmokePicker(string source) : IImagePicker
    {
        private readonly Queue<string> _savePaths = new();
        public string? PickImage() => source;
        public string? PickSavePath(string defaultFileName, string format) => _savePaths.Count > 0 ? _savePaths.Dequeue() : null;
        public void EnqueueSave(string path) => _savePaths.Enqueue(path);
    }

    private sealed class SvgResponseHandler(byte[] smartBytes, byte[] contourBytes) : HttpMessageHandler
    {
        private readonly Dictionary<string, string> _methods = new(StringComparer.Ordinal);
        public List<string> RequestOrder { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var route = request.RequestUri!.AbsolutePath.Trim('/');
            if (request.Method == HttpMethod.Get && route == "api/v1/health")
                return Json(new { status = "ok", engine = "Task07.1 deterministic fixture", device = "CPU", modelLoaded = false, vectorizationPipeline = "v2" });
            if (request.Method == HttpMethod.Get && route == "api/v1/desktop/contour-capabilities")
                return Json(new { experimentalEnabled = true, dependencyAvailable = true, dependencyVersion = "0.26.0", ready = true });
            if (request.Method == HttpMethod.Post && route == "api/v1/assets")
            {
                _ = await request.Content!.ReadAsByteArrayAsync(cancellationToken);
                return Json(new { assetId = "task071-shared-asset", fileName = "images_upscaled_8x.png", width = 4432, height = 4432, byteSize = 3220904, mode = "RGB" });
            }
            if (request.Method == HttpMethod.Post && route == "api/v1/vectorize/jobs")
            {
                using var document = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken));
                var method = document.RootElement.GetProperty("vector_method").GetString()!;
                var assetId = document.RootElement.GetProperty("asset_id").GetString()!;
                var jobId = method == "smart_reconstruction" ? "task071-smart" : "task071-contour";
                RequestOrder.Add(method);
                _methods.Add(jobId, method);
                return Json(new { jobId, assetId, state = "queued", progress = 0, stage = "queued", isIndeterminate = false });
            }
            if (request.Method == HttpMethod.Get && route.StartsWith("api/v1/jobs/", StringComparison.Ordinal))
            {
                var suffix = route["api/v1/jobs/".Length..];
                if (suffix.EndsWith("/result", StringComparison.Ordinal))
                {
                    var jobId = suffix[..^"/result".Length];
                    var bytes = _methods[jobId] == "smart_reconstruction" ? smartBytes : contourBytes;
                    var content = new ByteArrayContent(bytes);
                    content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/svg+xml");
                    return new HttpResponseMessage(HttpStatusCode.OK) { Content = content };
                }
                var vectorMethod = _methods[suffix];
                var smart = vectorMethod == "smart_reconstruction";
                return Json(new
                {
                    jobId = suffix,
                    assetId = "task071-shared-asset",
                    state = "succeeded",
                    progress = 100,
                    stage = "Done",
                    isIndeterminate = false,
                    resultPaths = smart ? 17 : 68,
                    resultSize = smart ? smartBytes.Length : contourBytes.Length,
                    resultEngine = smart ? "Vectorization V2" : "Contour-Preserving",
                    resultPipeline = smart ? "vectorization_v2" : "contour_preserving",
                    resultVectorMethod = vectorMethod,
                    resultMode = "auto",
                    resultTextMode = "outlined",
                    resultWarnings = Array.Empty<string>(),
                    resultGradients = smart ? 12 : 19
                });
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound) { Content = new StringContent($"Unknown route: {route}") };
        }

        private static HttpResponseMessage Json<T>(T value) => new(HttpStatusCode.OK)
        {
            Content = new StringContent(JsonSerializer.Serialize(value), Encoding.UTF8, "application/json")
        };
    }
}
