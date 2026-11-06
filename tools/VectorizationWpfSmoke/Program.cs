using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

internal static class Program
{
    private const string AssetId = "0123456789abcdef0123456789abcdef";
    private static readonly byte[] SmartSvg = Encoding.UTF8.GetBytes(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"4432\" height=\"4432\" viewBox=\"0 0 4432 4432\"><defs><linearGradient id=\"g\"><stop stop-color=\"#ffb222\"/><stop offset=\"1\" stop-color=\"#f40\"/></linearGradient></defs><path fill=\"url(#g)\" d=\"M200 400h400v400H200z\"/></svg>");
    private static readonly byte[] ContourSvg = Encoding.UTF8.GetBytes(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"4432\" height=\"4432\" viewBox=\"0 0 4432 4432\"><path fill=\"#ff7b20\" d=\"M300 300h600v600H300z\"/></svg>");

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
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
        var sourcePath = args.Length > 0
            ? Path.GetFullPath(args[0])
            : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "images_upscaled_8x.png");
        if (!File.Exists(sourcePath)) throw new FileNotFoundException("Pinned Task 07 raster fixture was not found.", sourcePath);

        var artifactDirectory = Path.Combine(Environment.CurrentDirectory, "backend", "artifacts", "contour_preserving", "task_07");
        Directory.CreateDirectory(artifactDirectory);
        var saveDirectory = Path.Combine(Path.GetTempPath(), "MediaStudioWpfSmoke", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(saveDirectory);
        var started = Stopwatch.StartNew();
        var observations = new List<object>();
        var memorySamples = new List<object>();
        var handler = new FakeBackendHandler();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1/") };
        var api = new MediaStudioApiClient(http);
        var picker = new FakeImagePicker(sourcePath);
        var health = await api.GetHealthAsync();
        Ensure(health.ContourReady && health.ContourDependencyVersion == "0.26.0",
            "Desktop capability endpoint was not merged into backend health state.");
        var vm = new VectorizeToolViewModel(picker, api, health);

        Ensure(vm.SelectedVectorMethod == "smart_reconstruction", "Smart Reconstruction V2 must be the default engine.");
        Ensure(vm.QualityMode == "auto" && vm.TextMode == "outlined", "Default quality/text settings changed unexpectedly.");
        vm.OpenImageCommand.Execute(null);
        Ensure(vm.HasImportedImage, "Pinned image did not load into the WPF view model.");
        var memoryAfterSource = Process.GetCurrentProcess().WorkingSet64;
        Ensure(vm.ContourReady && vm.CompareCommand.CanExecute(null), "Contour should be selectable when the backend flag and dependency are ready.");

        vm.QualityMode = "quality";
        vm.TextMode = "editable";
        await ((AsyncRelayCommand)vm.RunCommand).ExecuteAsync();
        Ensure(handler.VectorRequests.Count == 1 && handler.VectorRequests[0].VectorMethod == "smart_reconstruction",
            "Single-engine mode did not send Smart Reconstruction to the backend.");
        Ensure(vm.SmartHasResult, "Single Smart run did not route its result to the Smart preview.");
        vm.SelectedVectorMethod = "contour_preserving";
        await ((AsyncRelayCommand)vm.RunCommand).ExecuteAsync();
        Ensure(handler.VectorRequests.Count == 2 && handler.VectorRequests[1].VectorMethod == "contour_preserving",
            "Single-engine mode did not send Contour-Preserving to the backend.");
        Ensure(vm.ContourHasResult, "Single Contour run did not route its result to the Contour preview.");
        observations.Add(new
        {
            singleSmartMethod = handler.VectorRequests[0].VectorMethod,
            singleContourMethod = handler.VectorRequests[1].VectorMethod,
            smartResultRouted = vm.SmartHasResult,
            contourResultRouted = vm.ContourHasResult
        });

        var compareRequestStart = handler.VectorRequests.Count;
        var importCountBeforeCompare = handler.ImportCount;
        await vm.CompareCommand.ExecuteAsync();
        Ensure(vm.SmartHasResult && vm.ContourHasResult, "Both engines should produce results in the successful compare case.");
        var compareRequests = handler.VectorRequests.Skip(compareRequestStart).Take(2).ToArray();
        Ensure(handler.ImportCount == importCountBeforeCompare + 1, "Compare must import the source asset exactly once.");
        Ensure(compareRequests.Length == 2, "Compare must submit exactly two jobs.");
        Ensure(compareRequests[0].VectorMethod == "smart_reconstruction", "Smart method was not routed first.");
        Ensure(compareRequests[1].VectorMethod == "contour_preserving", "Contour method was not routed second.");
        Ensure(compareRequests[0].AssetId == compareRequests[1].AssetId, "Engines did not use the same source asset ID.");
        Ensure(compareRequests.All(request => request.Mode == "quality" && request.TextMode == "editable"), "Quality/text mode was not kept identical.");
        Ensure(handler.StartedAfterPriorJobFinished, "Compare launched jobs concurrently or before the first job finished.");
        Ensure(compareRequests[0].VectorMethod != compareRequests[1].VectorMethod, "Engine selection did not reach the API.");
        Ensure(vm.SmartPreviewImage?.PixelWidth <= 1024 && vm.ContourPreviewImage?.PixelWidth <= 1024, "SVG previews exceeded the bounded render dimensions.");
        Ensure(vm.SmartPreviewImage?.PixelHeight <= 1024 && vm.ContourPreviewImage?.PixelHeight <= 1024, "SVG preview heights exceeded the bounded render dimensions.");
        Ensure(vm.SmartStateText.StartsWith("Hoàn tất", StringComparison.Ordinal), "Smart progress state did not reach success.");
        Ensure(vm.ContourStateText.StartsWith("Hoàn tất", StringComparison.Ordinal), "Contour progress state did not reach success.");

        vm.PreviewBackground = "white";
        Ensure(vm.PreviewBackgroundBrush == System.Windows.Media.Brushes.White, "White compare background was not applied.");
        vm.PreviewBackground = "black";
        Ensure(vm.PreviewBackgroundBrush == System.Windows.Media.Brushes.Black, "Black compare background was not applied.");
        vm.PreviewBackground = "checkerboard";
        Ensure(vm.PreviewBackgroundBrush is System.Windows.Media.DrawingBrush, "Checkerboard compare background was not applied.");
        vm.SetZoomCommand.Execute("in");
        Ensure(vm.ZoomFactor > 1, "Zoom in did not update the shared zoom state.");
        vm.SetZoomCommand.Execute("fit");
        Ensure(Math.Abs(vm.ZoomFactor - 1) < .001 && Math.Abs(vm.PanX) < .001 && Math.Abs(vm.PanY) < .001,
            "Fit did not reset synchronized normalized zoom/pan.");

        var smartSavePath = Path.Combine(saveDirectory, "active_fox_smart.svg");
        var contourSavePath = Path.Combine(saveDirectory, "active_fox_contour.svg");
        picker.EnqueueSavePath(smartSavePath);
        picker.EnqueueSavePath(contourSavePath);
        await vm.SaveBothCommand.ExecuteAsync();
        Ensure(File.ReadAllBytes(smartSavePath).SequenceEqual(SmartSvg), "Smart SVG save did not preserve backend bytes.");
        Ensure(File.ReadAllBytes(contourSavePath).SequenceEqual(ContourSvg), "Contour SVG save did not preserve backend bytes.");
        observations.Add(new
        {
            sameSource = compareRequests[0].AssetId == compareRequests[1].AssetId,
            importCount = 1,
            requestMethods = compareRequests.Select(request => request.VectorMethod).ToArray(),
            qualityModes = compareRequests.Select(request => request.Mode).ToArray(),
            textModes = compareRequests.Select(request => request.TextMode).ToArray(),
            sequential = handler.StartedAfterPriorJobFinished,
            smartSvgBytesExact = true,
            contourSvgBytesExact = true
        });

        // Exercise repeated compare replacement. Each iteration holds only the newest
        // pair of capped SVG preview bitmaps; the original source bitmap is reused.
        var memoryPeakDuringCycles = Process.GetCurrentProcess().WorkingSet64;
        for (var index = 0; index < 24; index++)
        {
            await vm.CompareCommand.ExecuteAsync();
            Ensure(vm.SmartHasResult && vm.ContourHasResult, $"Repeated compare {index + 1} failed.");
            GC.Collect();
            GC.WaitForPendingFinalizers();
            GC.Collect();
            var process = Process.GetCurrentProcess();
            process.Refresh();
            memoryPeakDuringCycles = Math.Max(memoryPeakDuringCycles, process.WorkingSet64);
            memorySamples.Add(new { cycle = index + 1, workingSetBytes = process.WorkingSet64, privateBytes = process.PrivateMemorySize64, managedHeapBytes = GC.GetTotalMemory(false) });
        }

        handler.FailContour = true;
        await vm.CompareCommand.ExecuteAsync();
        Ensure(vm.SmartHasResult, "A Contour failure removed the successful Smart result.");
        Ensure(!vm.ContourHasResult && vm.ContourStateText.StartsWith("Thất bại", StringComparison.Ordinal),
            "Contour partial failure was not represented correctly.");
        var preservedSmartPath = Path.Combine(saveDirectory, "smart_after_partial_failure.svg");
        picker.EnqueueSavePath(preservedSmartPath);
        await vm.SaveSmartResultCommand.ExecuteAsync();
        Ensure(File.ReadAllBytes(preservedSmartPath).SequenceEqual(SmartSvg), "Smart result could not be saved after Contour failed.");
        observations.Add(new { smartPreserved = vm.SmartHasResult, contourFailed = !vm.ContourHasResult });

        handler.FailContour = false;
        handler.FailSmart = true;
        await vm.CompareCommand.ExecuteAsync();
        Ensure(!vm.SmartHasResult && vm.ContourHasResult, "A Smart failure removed or blocked the successful Contour result.");
        observations.Add(new { smartFailed = !vm.SmartHasResult, contourPreserved = vm.ContourHasResult });

        var sourceBytesBefore = File.ReadAllBytes(sourcePath);
        picker.EnqueueSavePath(sourcePath);
        await vm.SaveContourResultCommand.ExecuteAsync();
        Ensure(File.ReadAllBytes(sourcePath).SequenceEqual(sourceBytesBefore), "SVG saving overwrote the raster source.");

        handler.ContourCapabilityReady = false;
        var disabledHealth = await api.GetHealthAsync();
        var disabledVm = new VectorizeToolViewModel(picker, api, disabledHealth);
        disabledVm.OpenImageCommand.Execute(null);
        Ensure(!disabledVm.ContourReady && !disabledVm.CompareCommand.CanExecute(null), "Contour remained selectable when experimental support was disabled.");
        Ensure(disabledVm.SelectedVectorMethod == "smart_reconstruction", "Feature-flag state changed the default Smart engine.");

        handler.CapabilityEndpointAvailable = false;
        var olderBackendHealth = await api.GetHealthAsync();
        Ensure(olderBackendHealth.Status == "ok" && !olderBackendHealth.ContourReady,
            "An older backend without the capability endpoint should remain usable for Smart V2.");
        observations.Add(new
        {
            oldBackendWithoutCapabilityEndpoint = true,
            smartBackendHealthPreserved = olderBackendHealth.Status == "ok",
            contourDisabled = !olderBackendHealth.ContourReady
        });

        started.Stop();
        var memoryAfter = Process.GetCurrentProcess().WorkingSet64;
        var report = new
        {
            status = "PASS",
            sourcePath,
            sourceDimensions = $"{vm.PixelDimensions}",
            defaultMethod = "smart_reconstruction",
            contourEnabledFromHealth = true,
            disabledFeatureBehavior = "Contour and Compare unavailable; Smart remains default",
            compareRunCount = 27,
            results = observations,
            previewMaximumDimension = 1024,
            memory = new { workingSetAfterSourceLoadBytes = memoryAfterSource, peakDuringRepeatedCompareBytes = memoryPeakDuringCycles, workingSetAfterRepeatedRunsBytes = memoryAfter },
            durationSeconds = started.Elapsed.TotalSeconds,
            manualWpfQa = "PENDING"
        };
        var outputPath = Path.Combine(artifactDirectory, "wpf_viewmodel_tests.json");
        await File.WriteAllTextAsync(outputPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
        var memoryReport = new
        {
            sourcePath,
            sourceDimensions = vm.PixelDimensions,
            svgPreviewMaximumDimension = 1024,
            repeatedCompareCycles = memorySamples.Count,
            sampling = "WPF ViewModel smoke harness working set/private bytes/managed heap after collection; not a manual UI measurement",
            workingSetAfterSourceLoadBytes = memoryAfterSource,
            peakWorkingSetBytes = memoryPeakDuringCycles,
            workingSetAfterAllRunsBytes = memoryAfter,
            cycles = memorySamples
        };
        await File.WriteAllTextAsync(Path.Combine(artifactDirectory, "resource_usage.json"), JsonSerializer.Serialize(memoryReport, new JsonSerializerOptions { WriteIndented = true }));
        var saveReport = new
        {
            savedSmartSvgBytesExact = File.ReadAllBytes(smartSavePath).SequenceEqual(SmartSvg),
            savedContourSvgBytesExact = File.ReadAllBytes(contourSavePath).SequenceEqual(ContourSvg),
            sourceOverwritePrevented = File.ReadAllBytes(sourcePath).SequenceEqual(sourceBytesBefore),
            saveBothPromptsUsed = 2,
            outcome = "PASS"
        };
        await File.WriteAllTextAsync(Path.Combine(artifactDirectory, "wpf_save_validation.json"), JsonSerializer.Serialize(saveReport, new JsonSerializerOptions { WriteIndented = true }));
        Directory.Delete(saveDirectory, recursive: true);
        Console.WriteLine(JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    }

    private static void Ensure(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private sealed class FakeImagePicker(string sourcePath) : IImagePicker
    {
        private readonly Queue<string?> _savePaths = new();
        public string? PickImage() => sourcePath;
        public string? PickSavePath(string defaultFileName, string format) => _savePaths.Count > 0 ? _savePaths.Dequeue() : null;
        public void EnqueueSavePath(string? path) => _savePaths.Enqueue(path);
    }

    private sealed class FakeBackendHandler : HttpMessageHandler
    {
        private readonly Dictionary<string, string> _jobMethods = new(StringComparer.Ordinal);
        private readonly HashSet<string> _completedJobs = new(StringComparer.Ordinal);
        private readonly List<string> _jobOrder = [];
        public List<VectorRequestObservation> VectorRequests { get; } = [];
        public int ImportCount { get; private set; }
        public bool FailContour { get; set; }
        public bool FailSmart { get; set; }
        public bool ContourCapabilityReady { get; set; } = true;
        public bool CapabilityEndpointAvailable { get; set; } = true;
        public bool StartedAfterPriorJobFinished { get; private set; } = true;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath.Trim('/');
            if (request.Method == HttpMethod.Get && path == "api/v1/health")
                return Json(new { status = "ok", engine = "Real-ESRGAN", device = "CPU", modelLoaded = false, vectorizationPipeline = "v2" });
            if (request.Method == HttpMethod.Get && path == "api/v1/desktop/contour-capabilities")
            {
                if (!CapabilityEndpointAvailable)
                    return new HttpResponseMessage(HttpStatusCode.NotFound);
                return Json(new { experimentalEnabled = ContourCapabilityReady, dependencyAvailable = ContourCapabilityReady, dependencyVersion = ContourCapabilityReady ? "0.26.0" : null, ready = ContourCapabilityReady });
            }
            if (request.Method == HttpMethod.Post && path == "api/v1/assets")
            {
                _ = await request.Content!.ReadAsByteArrayAsync(cancellationToken);
                ImportCount++;
                return Json(new { assetId = AssetId, fileName = "images_upscaled_8x.png", width = 4432, height = 4432, byteSize = 123, mode = "RGBA" });
            }

            if (request.Method == HttpMethod.Post && path == "api/v1/vectorize/jobs")
            {
                using var body = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken));
                var root = body.RootElement;
                var method = root.GetProperty("vector_method").GetString()!;
                var assetId = root.GetProperty("asset_id").GetString()!;
                var mode = root.GetProperty("mode").GetString()!;
                var textMode = root.GetProperty("text_mode").GetString()!;
                if (_jobOrder.Count > 0 && !_completedJobs.Contains(_jobOrder[^1])) StartedAfterPriorJobFinished = false;
                var jobId = $"job{_jobOrder.Count + 1}";
                _jobMethods[jobId] = method;
                _jobOrder.Add(jobId);
                VectorRequests.Add(new VectorRequestObservation(assetId, method, mode, textMode));
                return Json(new { jobId, assetId, state = "queued", progress = 0, stage = "Waiting", isIndeterminate = false });
            }

            if (request.Method == HttpMethod.Get && path.StartsWith("api/v1/jobs/", StringComparison.Ordinal))
            {
                var suffix = path["api/v1/jobs/".Length..];
                if (suffix.EndsWith("/result", StringComparison.Ordinal))
                {
                    var jobId = suffix[..^"/result".Length];
                    var method = _jobMethods[jobId];
                    return new HttpResponseMessage(HttpStatusCode.OK)
                    {
                        Content = new ByteArrayContent(method == "smart_reconstruction" ? SmartSvg : ContourSvg)
                    };
                }

                var currentMethod = _jobMethods[suffix];
                var fail = currentMethod == "smart_reconstruction" ? FailSmart : FailContour;
                _completedJobs.Add(suffix);
                if (fail)
                {
                    return Json(new
                    {
                        jobId = suffix,
                        assetId = AssetId,
                        state = "failed",
                        progress = 0,
                        stage = "Failed",
                        isIndeterminate = false,
                        error = "Synthetic engine failure",
                        errorCode = currentMethod == "contour_preserving" ? "CONTOUR_PIPELINE_FAILED" : "SMART_TEST_FAILURE",
                        errorDetails = new Dictionary<string, string>()
                    });
                }
                return Json(new
                {
                    jobId = suffix,
                    assetId = AssetId,
                    state = "succeeded",
                    progress = 100,
                    stage = "Done",
                    isIndeterminate = false,
                    resultPaths = currentMethod == "smart_reconstruction" ? 5 : 7,
                    resultSize = currentMethod == "smart_reconstruction" ? SmartSvg.Length : ContourSvg.Length,
                    resultEngine = currentMethod == "smart_reconstruction" ? "Vectorization V2" : "Contour-Preserving",
                    resultPipeline = currentMethod == "smart_reconstruction" ? "vectorization_v2" : "contour_preserving",
                    resultVectorMethod = currentMethod,
                    resultMode = "quality",
                    resultTextMode = "editable",
                    resultWarnings = Array.Empty<string>(),
                    resultGradients = currentMethod == "smart_reconstruction" ? 1 : 0
                });
            }

            return new HttpResponseMessage(HttpStatusCode.NotFound) { Content = new StringContent("unknown path") };
        }

        private static HttpResponseMessage Json<T>(T value) => new(HttpStatusCode.OK)
        {
            Content = new StringContent(JsonSerializer.Serialize(value), Encoding.UTF8, "application/json")
        };
    }

    private sealed record VectorRequestObservation(string AssetId, string VectorMethod, string Mode, string TextMode);
}
