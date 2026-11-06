using System.Diagnostics;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace MediaStudio.Desktop.Services;

public sealed class MediaStudioApiClient(HttpClient httpClient)
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly HttpClient _httpClient = httpClient;

    public async Task<BackendHealth> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("api/v1/health", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var health = (await response.Content.ReadFromJsonAsync<BackendHealth>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả trạng thái sẵn sàng.");
        return health;
    }

    public async Task<ImportedAsset> ImportImageAsync(string filePath, CancellationToken cancellationToken = default)
    {
        await using var file = File.OpenRead(filePath);
        using var multipart = new MultipartFormDataContent();
        using var fileContent = new StreamContent(file);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue(GetContentType(filePath));
        multipart.Add(fileContent, "file", Path.GetFileName(filePath));

        using var response = await _httpClient.PostAsync("api/v1/assets", multipart, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<ImportedAsset>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả thông tin ảnh đã nhập.");
    }

    public async Task<BackendJob> StartUpscaleAsync(UpscaleRequest request, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/upscale/jobs", request, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<BackendJob>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ nâng cấp ảnh.");
    }

    public async Task<BackendJob> StartVectorizeAsync(VectorizeRequest request, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/vectorize/jobs", request, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<BackendJob>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ vector hóa ảnh.");
    }

    public async Task<BackendJob> StartDieCutAsync(DieCutRequest request, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/die-cut/jobs", request, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<BackendJob>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ đường bế.");
    }

    public async Task<BackendJob> GetJobAsync(string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync($"api/v1/jobs/{Uri.EscapeDataString(jobId)}", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<BackendJob>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả trạng thái tác vụ.");
    }

    public async Task<byte[]> DownloadResultAsync(string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync($"api/v1/jobs/{Uri.EscapeDataString(jobId)}/result", HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }

    public async Task<VideoEditorCapabilitiesDto> GetVideoEditorCapabilitiesAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("api/v1/video/capabilities", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoEditorCapabilitiesDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả khả năng Video Editor.");
    }

    public async Task<IReadOnlyList<VideoTemplateDto>> GetVideoTemplatesAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("api/v1/video/templates", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var result = await response.Content.ReadFromJsonAsync<VideoTemplateListResponse>(JsonOptions, cancellationToken)
            ?? throw new InvalidOperationException("Backend không trả danh mục mẫu video.");
        return result.Templates;
    }

    public async Task<string> PrepareMediaSelectionAsync(string templateId, string version, Dictionary<string, string> bindings)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/video/media-selection/prepare",
            new { templateId, templateDefinitionVersion = version, bindings }, JsonOptions);
        await EnsureSuccessAsync(response, CancellationToken.None);
        return await response.Content.ReadAsStringAsync();
    }

    public async Task<byte[]> RenderStoryPagePreviewAsync(
        string templateId, int page, Dictionary<string, string> bindings, int width = 540,
        CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/stories/{Uri.EscapeDataString(templateId)}/preview",
            new { bindings, page, width }, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }

    public async Task<StoryRenderResultDto> RenderStoryPageAsync(
        string templateId, string version, Dictionary<string, string> bindings, int page, string runId,
        string format = "png", CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/stories/{Uri.EscapeDataString(templateId)}/render",
            new { templateDefinitionVersion = version, bindings, format, page, runId }, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadFromJsonAsync<StoryRenderResultDto>(JsonOptions, cancellationToken)
            ?? throw new InvalidOperationException("Backend không trả kết quả dựng trang.");
    }

    public async Task<StoryRenderResultDto> RenderStoryTemplateAsync(
        string templateId, string version, Dictionary<string, string> bindings, string format = "png",
        CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/stories/{Uri.EscapeDataString(templateId)}/render",
            new { templateDefinitionVersion = version, bindings, format }, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadFromJsonAsync<StoryRenderResultDto>(JsonOptions, cancellationToken)
            ?? throw new InvalidOperationException("Backend không trả kết quả dựng ảnh.");
    }

    public async Task<TemplateProcessingJobDto> StartTemplateProcessingAsync(
        string templateId, string version, string selectionSessionId,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/video/processing-jobs",
            new { templateId, templateDefinitionVersion = version, selectionSessionId, bindings },
            JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<TemplateProcessingJobDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ áp dụng mẫu.");
    }

    public async Task<TemplateProcessingJobDto> GetTemplateProcessingJobAsync(
        string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/processing-jobs/{Uri.EscapeDataString(jobId)}", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<TemplateProcessingJobDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả trạng thái áp dụng mẫu.");
    }

    public async Task<IReadOnlyList<VideoMediaDto>> GetVideoMediaAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("api/v1/video/media", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var result = await response.Content.ReadFromJsonAsync<VideoMediaListResponse>(JsonOptions, cancellationToken)
            ?? throw new InvalidOperationException("Backend không trả danh sách media.");
        return result.Media;
    }

    public async Task<VideoMediaDto> ImportVideoMediaAsync(string filePath, CancellationToken cancellationToken = default)
    {
        await using var file = File.OpenRead(filePath);
        using var multipart = new MultipartFormDataContent();
        using var fileContent = new StreamContent(file);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue(GetContentType(filePath));
        multipart.Add(fileContent, "file", Path.GetFileName(filePath));
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/v1/video/media") { Content = multipart };
        using var response = await _httpClient.SendAsync(request,
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoMediaDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả metadata media vừa nhập.");
    }

    public async Task DeleteVideoLibraryMediaAsync(IReadOnlyList<string> ids)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/video/media/library-delete", ids, JsonOptions);
        await EnsureSuccessAsync(response, CancellationToken.None);
    }

    public async Task<byte[]> GetVideoMediaThumbnailAsync(string assetId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/media/{Uri.EscapeDataString(assetId)}/thumbnail",
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }

    public async Task<byte[]> GetVideoMediaFrameAsync(string assetId, int timestampMs,
        CancellationToken cancellationToken = default)
    {
        var boundedTimestamp = Math.Max(0, timestampMs);
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/media/{Uri.EscapeDataString(assetId)}/frame?timestamp_ms={boundedTimestamp}",
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }

    public async Task<byte[]> GetVideoMediaFilmstripAsync(string assetId, int frameCount = 24,
        CancellationToken cancellationToken = default)
    {
        var boundedCount = Math.Clamp(frameCount, 4, 24);
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/media/{Uri.EscapeDataString(assetId)}/filmstrip?frames={boundedCount}",
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }

    public async Task<VideoWaveformDto> GetVideoMediaWaveformAsync(string assetId, int sampleCount = 480,
        CancellationToken cancellationToken = default)
    {
        var boundedCount = Math.Clamp(sampleCount, 100, 2000);
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/media/{Uri.EscapeDataString(assetId)}/waveform?samples={boundedCount}",
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoWaveformDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả dữ liệu waveform.");
    }

    public async Task SaveVideoMediaContentAsync(string assetId, string destinationPath, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/media/{Uri.EscapeDataString(assetId)}/content",
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var fullPath = Path.GetFullPath(destinationPath);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        var temporaryPath = fullPath + ".partial";
        try
        {
            await using (var output = File.Create(temporaryPath))
                await response.Content.CopyToAsync(output, cancellationToken);
            File.Move(temporaryPath, fullPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }

    public async Task<VideoProjectDto> CreateVideoProjectAsync(
        string templateId, string? title = null, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "api/v1/video/projects", new { templateId, title }, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoProjectDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được dự án video.");
    }

    public async Task<VideoProjectDto> CreateBlankVideoProjectAsync(
        string title = "Dự án trống", CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "api/v1/video/projects/blank", new { title }, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoProjectDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được dự án trống.");
    }

    public async Task<VideoProjectDto> GetVideoProjectAsync(string projectId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectId)}", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoProjectDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả dự án video.");
    }

    public async Task<IReadOnlyList<VideoProjectDto>> GetVideoProjectsAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("api/v1/video/projects", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var result = await response.Content.ReadFromJsonAsync<VideoProjectListResponse>(JsonOptions, cancellationToken)
            ?? throw new InvalidOperationException("Backend không trả danh sách dự án video.");
        return result.Projects;
    }

    public async Task<VideoProjectDto> SaveVideoProjectAsync(
        VideoProjectDto project, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PutAsJsonAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(project.ProjectId)}", project, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoProjectDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không lưu được dự án video.");
    }

    public async Task<VideoCompositionPreviewFrame> RenderVideoCompositionPreviewAsync(
        VideoProjectDto projectSnapshot, long timestampTicks, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectSnapshot.ProjectId)}/preview/frame?timestamp_ticks={Math.Max(0, timestampTicks)}",
            projectSnapshot, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var bytes = await response.Content.ReadAsByteArrayAsync(cancellationToken);
        if (bytes.Length < 8 || !bytes.AsSpan(0, 8).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }))
            throw new InvalidOperationException("Backend preview không trả về PNG hợp lệ.");
        return new VideoCompositionPreviewFrame(
            bytes,
            ReadIntHeader(response, "X-Composition-Graph-Version"),
            ReadIntHeader(response, "X-Composition-Frame-Index"),
            ReadHeader(response, "X-Composition-Source-Fingerprint"),
            ReadHeader(response, "X-Composition-Renderer"),
            ReadIntHeader(response, "X-Composition-Project-Revision"));
    }

    public async Task<VideoOverlayEditLayerDto> GetVideoOverlayEditLayerAsync(
        VideoProjectDto projectSnapshot, string clipId, long timestampTicks, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectSnapshot.ProjectId)}/preview/overlay-edit"
            + $"?clip_id={Uri.EscapeDataString(clipId)}&timestamp_ticks={Math.Max(0, timestampTicks)}",
            projectSnapshot, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadFromJsonAsync<VideoOverlayEditLayerDto>(JsonOptions, cancellationToken)
            ?? throw new InvalidOperationException("Backend không trả dữ liệu chỉnh ảnh.");
    }

    public async Task<VideoCompositionPreviewVideo> RenderVideoCompositionPreviewVideoAsync(
        VideoProjectDto projectSnapshot, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectSnapshot.ProjectId)}/preview/video",
            projectSnapshot, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        var bytes = await response.Content.ReadAsByteArrayAsync(cancellationToken);
        if (bytes.Length < 12 || !bytes.AsSpan(4, 4).SequenceEqual("ftyp"u8))
            throw new InvalidOperationException("Backend không trả về video MP4 preview hợp lệ.");
        return new VideoCompositionPreviewVideo(
            bytes,
            ReadIntHeader(response, "X-Composition-Project-Revision"),
            ReadHeader(response, "X-Composition-Source-Fingerprint"));
    }

    public async Task<VideoRenderJobDto> StartVideoRenderAsync(
        string projectId, string quality = "standard", CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectId)}/render-jobs",
            new { quality, videoCodec = "h264" }, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoRenderJobDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ xuất video.");
    }

    public async Task<VideoCreatorExportCapabilitiesDto> GetVideoCreatorExportCapabilitiesAsync(
        string projectId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectId)}/export-capabilities", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoCreatorExportCapabilitiesDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả về capability xuất video.");
    }

    public async Task<VideoRenderJobDto> StartVideoCreatorExportAsync(
        string projectId, VideoCreatorExportRequestDto request, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            $"api/v1/video/projects/{Uri.EscapeDataString(projectId)}/export-jobs", request, JsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoRenderJobDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được export job.");
    }

    public async Task<VideoRenderJobDto> GetVideoRenderJobAsync(string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/jobs/{Uri.EscapeDataString(jobId)}", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<VideoRenderJobDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả trạng thái xuất video.");
    }

    public async Task CancelVideoRenderJobAsync(string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.DeleteAsync(
            $"api/v1/video/jobs/{Uri.EscapeDataString(jobId)}", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
    }

    public async Task<byte[]> DownloadVideoRenderResultAsync(string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync(
            $"api/v1/video/jobs/{Uri.EscapeDataString(jobId)}/result",
            HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }

    public async Task StopBackendAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsync("api/v1/shutdown", content: null, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
    }

    // ---------------------------------------------------------------- Fashion Studio (Qwen-Image-Edit)
    public async Task<FashionStatusDto> GetFashionStatusAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("api/v1/fashion/status", cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<FashionStatusDto>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không trả trạng thái Fashion Studio.");
    }

    public async Task<BackendJob> StartFashionDownloadAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsync("api/v1/fashion/download", content: null, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<BackendJob>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ tải model.");
    }

    public async Task<BackendJob> StartFashionJobAsync(FashionJobRequestDto request, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync("api/v1/fashion/jobs", request, FashionJsonOptions, cancellationToken);
        await EnsureSuccessAsync(response, cancellationToken);
        return (await response.Content.ReadFromJsonAsync<BackendJob>(JsonOptions, cancellationToken))
            ?? throw new InvalidOperationException("Backend không tạo được tác vụ Fashion Studio.");
    }

    private static readonly JsonSerializerOptions FashionJsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    };

    private static async Task EnsureSuccessAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        string? detail = null;
        string? code = null;
        try
        {
            using var payload = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(cancellationToken), cancellationToken: cancellationToken);
            if (payload.RootElement.TryGetProperty("detail", out var detailElement))
            {
                if (detailElement.ValueKind == JsonValueKind.Object)
                {
                    if (detailElement.TryGetProperty("code", out var codeElement)) code = codeElement.GetString();
                    if (detailElement.TryGetProperty("message", out var messageElement)) detail = messageElement.GetString();
                    detail ??= detailElement.ToString();
                }
                else
                {
                    detail = detailElement.ValueKind == JsonValueKind.String ? detailElement.GetString() : detailElement.ToString();
                }
            }
        }
        catch (JsonException)
        {
        }

        throw new BackendApiException(response.StatusCode, code, detail ?? $"Lỗi backend ({(int)response.StatusCode}).");
    }

    private static string ReadHeader(HttpResponseMessage response, string name) =>
        response.Headers.TryGetValues(name, out var values) ? values.FirstOrDefault() ?? "" : "";

    private static int ReadIntHeader(HttpResponseMessage response, string name) =>
        int.TryParse(ReadHeader(response, name), out var value) ? value : 0;

    private static string GetContentType(string filePath) => Path.GetExtension(filePath).ToLowerInvariant() switch
    {
        ".jpg" or ".jpeg" => "image/jpeg",
        ".png" => "image/png",
        ".bmp" => "image/bmp",
        ".tif" or ".tiff" => "image/tiff",
        ".webp" => "image/webp",
        ".mp4" or ".m4v" => "video/mp4",
        ".mov" => "video/quicktime",
        ".mkv" => "video/x-matroska",
        ".webm" => "video/webm",
        ".avi" => "video/x-msvideo",
        ".mp3" => "audio/mpeg",
        ".wav" => "audio/wav",
        ".m4a" => "audio/mp4",
        ".aac" => "audio/aac",
        ".ogg" => "audio/ogg",
        ".flac" => "audio/flac",
        _ => "application/octet-stream"
    };
}

public sealed class VideoTemplateListResponse
{
    public List<VideoTemplateDto> Templates { get; set; } = [];
}

public sealed class VideoMediaListResponse
{
    public List<VideoMediaDto> Media { get; set; } = [];
}

public sealed class VideoProjectListResponse
{
    public List<VideoProjectDto> Projects { get; set; } = [];
}

public sealed class BackendProcessHost : IAsyncDisposable
{
    private readonly object _outputLock = new();
    private readonly List<string> _recentOutput = [];
    private Process? _process;
    private HttpClient? _httpClient;
    private string? _logPath;

    public MediaStudioApiClient? ApiClient { get; private set; }
    public BackendHealth? Health { get; private set; }

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        var packagedBackend = Path.Combine(AppContext.BaseDirectory, "MediaStudio.Backend.exe");
        var backendRoot = File.Exists(packagedBackend) ? AppContext.BaseDirectory : FindBackendRoot();
        var appData = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MediaStudio");
        var modelsDirectory = Environment.GetEnvironmentVariable("MEDIASTUDIO_MODELS_DIRECTORY")
            ?? Path.Combine(appData, "models", "realesrgan");
        var dataDirectory = Environment.GetEnvironmentVariable("MEDIASTUDIO_DATA_DIRECTORY")
            ?? Path.Combine(appData, "workspace");
        var backendLogPath = Environment.GetEnvironmentVariable("MEDIASTUDIO_BACKEND_LOG_PATH")
            ?? Path.Combine(appData, "backend.log");
        Directory.CreateDirectory(appData);
        Directory.CreateDirectory(dataDirectory);
        Directory.CreateDirectory(modelsDirectory);
        _logPath = backendLogPath;

        var port = GetFreeLoopbackPort();
        var token = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        var baseAddress = new Uri($"http://127.0.0.1:{port}/");
        var startInfo = CreateStartInfo(backendRoot, port, token, dataDirectory, modelsDirectory);
        var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, eventArgs) => RecordOutput(eventArgs.Data);
        process.ErrorDataReceived += (_, eventArgs) => RecordOutput(eventArgs.Data);
        process.Exited += (_, _) =>
        {
            try { RecordOutput($"[backend process exited] pid={process.Id} exitCode={process.ExitCode}"); }
            catch (InvalidOperationException) { RecordOutput("[backend process exited] exit code unavailable"); }
        };
        _process = process;
        if (!process.Start())
        {
            throw new InvalidOperationException("Không khởi động được Python backend.");
        }
        RecordOutput($"[backend process started] pid={process.Id} port={port}");
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        _httpClient = new HttpClient { BaseAddress = baseAddress, Timeout = Timeout.InfiniteTimeSpan };
        _httpClient.DefaultRequestHeaders.Add("X-Media-Studio-Token", token);
        ApiClient = new MediaStudioApiClient(_httpClient);

        var deadline = DateTime.UtcNow.AddSeconds(35);
        Exception? lastError = null;
        while (DateTime.UtcNow < deadline && !cancellationToken.IsCancellationRequested)
        {
            if (_process.HasExited)
            {
                throw new InvalidOperationException($"Python backend đã dừng với mã {_process.ExitCode}. {GetRecentOutput()}");
            }

            try
            {
                Health = await ApiClient.GetHealthAsync(cancellationToken);
                return;
            }
            catch (Exception error) when (error is HttpRequestException or TaskCanceledException or InvalidOperationException)
            {
                lastError = error;
                await Task.Delay(250, cancellationToken);
            }
        }

        await StopAsync();
        throw new InvalidOperationException($"Python backend không phản hồi. {GetRecentOutput()}", lastError);
    }

    public async Task StopAsync()
    {
        if (_process is null)
        {
            return;
        }

        if (!_process.HasExited && ApiClient is not null)
        {
            try
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                await ApiClient.StopBackendAsync(timeout.Token);
            }
            catch
            {
            }
        }

        try
        {
            await _process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(3));
        }
        catch (TimeoutException)
        {
            try { _process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            try { await _process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(2)); } catch (TimeoutException) { }
        }

        _httpClient?.Dispose();
        _httpClient = null;
        ApiClient = null;
        _process.Dispose();
        _process = null;
    }

    public async ValueTask DisposeAsync() => await StopAsync();

    private ProcessStartInfo CreateStartInfo(string backendRoot, int port, string token, string dataDirectory, string modelsDirectory)
    {
        var packagedBackend = Path.Combine(AppContext.BaseDirectory, "MediaStudio.Backend.exe");
        var pythonEnvironment = Path.Combine(backendRoot, ".venv", "Scripts", "python.exe");
        var startInfo = new ProcessStartInfo
        {
            WorkingDirectory = backendRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        startInfo.Environment["MEDIASTUDIO_SESSION_TOKEN"] = token;
        startInfo.Environment["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] =
            Environment.GetEnvironmentVariable("MEDIASTUDIO_CONTOUR_EXPERIMENTAL") ?? "0";
        startInfo.Environment["MEDIASTUDIO_FOREGROUND_PROTECTION_LAB"] =
            Environment.GetEnvironmentVariable("MEDIASTUDIO_FOREGROUND_PROTECTION_LAB") ?? "1";
        startInfo.Environment["MEDIASTUDIO_GUIDED_BACKGROUND_EXCLUSION"] =
            Environment.GetEnvironmentVariable("MEDIASTUDIO_GUIDED_BACKGROUND_EXCLUSION") ?? "1";
        var appLocalVideoEngine = Path.Combine(AppContext.BaseDirectory, "mediastudio_video_engine.dll");
        if (File.Exists(appLocalVideoEngine))
            startInfo.Environment["MEDIASTUDIO_VIDEO_ENGINE_PATH"] = appLocalVideoEngine;

        if (File.Exists(packagedBackend))
        {
            startInfo.FileName = packagedBackend;
        }
        else
        {
            startInfo.FileName = File.Exists(pythonEnvironment) ? pythonEnvironment : "python.exe";
            startInfo.ArgumentList.Add("-m");
            startInfo.ArgumentList.Add("mediastudio.desktop_main");
            startInfo.Environment["PYTHONPATH"] = backendRoot;
            startInfo.Environment["PYTHONUTF8"] = "1";
        }

        startInfo.ArgumentList.Add("--host");
        startInfo.ArgumentList.Add("127.0.0.1");
        startInfo.ArgumentList.Add("--port");
        startInfo.ArgumentList.Add(port.ToString(System.Globalization.CultureInfo.InvariantCulture));
        startInfo.ArgumentList.Add("--data-directory");
        startInfo.ArgumentList.Add(dataDirectory);
        startInfo.ArgumentList.Add("--models-directory");
        startInfo.ArgumentList.Add(modelsDirectory);
        return startInfo;
    }

    private static string FindBackendRoot()
    {
        var candidates = new[] { AppContext.BaseDirectory, Environment.CurrentDirectory };
        foreach (var candidate in candidates)
        {
            var directory = new DirectoryInfo(candidate);
            while (directory is not null)
            {
                var backendDirectory = Path.Combine(directory.FullName, "backend");
                if (File.Exists(Path.Combine(backendDirectory, "mediastudio", "main.py")))
                {
                    return backendDirectory;
                }
                if (File.Exists(Path.Combine(directory.FullName, "mediastudio", "main.py")))
                {
                    return directory.FullName;
                }
                directory = directory.Parent;
            }
        }
        throw new DirectoryNotFoundException("Không tìm thấy backend/mediastudio. Hãy chạy backend/setup.ps1 trước.");
    }

    private static int GetFreeLoopbackPort()
    {
        using var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        return ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
    }

    private void RecordOutput(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        lock (_outputLock)
        {
            _recentOutput.Add(line);
            if (_recentOutput.Count > 30) _recentOutput.RemoveAt(0);
            if (_logPath is not null)
            {
                try { File.AppendAllText(_logPath, $"{DateTimeOffset.Now:O} {line}{Environment.NewLine}"); } catch (IOException) { }
            }
        }
    }

    private string GetRecentOutput()
    {
        lock (_outputLock) return string.Join(" | ", _recentOutput.TakeLast(8));
    }
}

public sealed class BackendHealth
{
    public string Status { get; set; } = "";
    public string Engine { get; set; } = "";
    public string Device { get; set; } = "";
    public bool ModelLoaded { get; set; }
    public string VectorizationPipeline { get; set; } = "";
    public bool ContourExperimentalEnabled { get; set; }
    public bool ContourDependencyAvailable { get; set; }
    public string? ContourDependencyVersion { get; set; }
    public bool ContourReady { get; set; }
    public bool ForegroundProtectionLabEnabled { get; set; }
    public bool GuidedBackgroundExclusionEnabled { get; set; }
}

public sealed class BackendApiException(HttpStatusCode statusCode, string? code, string message)
    : InvalidOperationException(message)
{
    public HttpStatusCode StatusCode { get; } = statusCode;
    public string? Code { get; } = code;
}

public sealed class ImportedAsset
{
    public string AssetId { get; set; } = "";
    public string FileName { get; set; } = "";
    public int Width { get; set; }
    public int Height { get; set; }
    public long ByteSize { get; set; }
    public string Mode { get; set; } = "";
}

public sealed class UpscaleRequest
{
    [JsonPropertyName("asset_id")]
    public string AssetId { get; set; } = "";
    public int Scale { get; set; }
    public string Model { get; set; } = "Real-ESRGAN";
    [JsonPropertyName("reduce_noise")]
    public bool ReduceNoise { get; set; }
    public bool Sharpen { get; set; }
    [JsonPropertyName("output_format")]
    public string OutputFormat { get; set; } = "PNG";
}

public sealed class VectorizeRequest
{
    [JsonPropertyName("asset_id")]
    public string AssetId { get; set; } = "";
    public string Engine { get; set; } = "auto";
    public string Mode { get; set; } = "auto";
    [JsonPropertyName("color_count")]
    public int? ColorCount { get; set; }
    public int? Simplification { get; set; }
    [JsonPropertyName("smooth_paths")]
    public bool SmoothPaths { get; set; } = true;
    [JsonPropertyName("transparent_background")]
    public bool TransparentBackground { get; set; } = true;
    [JsonPropertyName("text_mode")]
    public string TextMode { get; set; } = "outlined";
    [JsonPropertyName("vector_method")]
    public string? VectorMethod { get; set; }
    [JsonPropertyName("detail")]
    public int? Detail { get; set; }
    [JsonPropertyName("output_mode")]
    public string OutputMode { get; set; } = "cutout";
}

public sealed class DieCutRequest
{
    [JsonPropertyName("asset_id")]
    public string AssetId { get; set; } = "";
    [JsonPropertyName("offset_mm")]
    public double OffsetMillimeters { get; set; }
    [JsonPropertyName("artwork_width_mm")]
    public double ArtworkWidthMillimeters { get; set; }
    [JsonPropertyName("auto_detect")]
    public bool AutoDetect { get; set; }
    [JsonPropertyName("smooth_path")]
    public bool SmoothPath { get; set; }
    public string Complexity { get; set; } = "Vừa";
    public List<DieCutStrokeRequest> Strokes { get; set; } = [];
}

public sealed class DieCutStrokeRequest
{
    public string Mode { get; set; } = "foreground";
    public List<DieCutPointRequest> Points { get; set; } = [];
}

public sealed class DieCutPointRequest
{
    public double X { get; set; }
    public double Y { get; set; }
}

public sealed class BackendJob
{
    public string JobId { get; set; } = "";
    public string AssetId { get; set; } = "";
    public string State { get; set; } = "";
    public int Progress { get; set; }
    public string Stage { get; set; } = "";
    public bool IsIndeterminate { get; set; }
    public int? ResultWidth { get; set; }
    public int? ResultHeight { get; set; }
    public long? ResultSize { get; set; }
    public int? ResultPaths { get; set; }
    public string? ResultEngine { get; set; }
    public string? ResultImageType { get; set; }
    public string? ResultMode { get; set; }
    public int? ResultTextLayers { get; set; }
    public int? ResultGradients { get; set; }
    public double? ResultProcessingTimeMs { get; set; }
    public int? ResultInputWidth { get; set; }
    public int? ResultInputHeight { get; set; }
    public int? ResultTraceWidth { get; set; }
    public int? ResultTraceHeight { get; set; }
    public int? ResultRegions { get; set; }
    public string? ResultPipeline { get; set; }
    public string? ResultTextMode { get; set; }
    public int? ResultEditableTextCount { get; set; }
    public int? ResultOutlinedTextCount { get; set; }
    public int? ResultAppearanceLayers { get; set; }
    public int? ResultClipPaths { get; set; }
    public List<string> ResultWarnings { get; set; } = [];
    public List<ResultWarningDetail> ResultWarningDetails { get; set; } = [];
    public int? ResultTextElementCount { get; set; }
    public int? ResultOutlinedTextPathCount { get; set; }
    public int? ResultEmbeddedRasterCount { get; set; }
    public Dictionary<string, int> ResultPhaseTimingsMs { get; set; } = [];
    public string? Error { get; set; }
    public string? ErrorCode { get; set; }
    public Dictionary<string, JsonElement> ErrorDetails { get; set; } = [];
    public string? ResultVectorMethod { get; set; }
    public Dictionary<string, JsonElement> ResultEngineMetadata { get; set; } = [];
}

public sealed class ResultWarningDetail
{
    public string Level { get; set; } = "WARNING";
    public string Code { get; set; } = "UNKNOWN";
    public string Message { get; set; } = "";
}

public sealed class FashionStatusDto
{
    public string State { get; set; } = "";
    public string Message { get; set; } = "";
    public string Model { get; set; } = "";
    public List<string> MissingPackages { get; set; } = [];
    public string Gpu { get; set; } = "";
    public double VramGb { get; set; }
    public string MemoryMode { get; set; } = "";
    public bool ModelDownloaded { get; set; }
    public bool ModelLoaded { get; set; }
    public bool Lightning { get; set; }
    public List<string> ScenePresets { get; set; } = [];
    public List<string> ViewPresets { get; set; } = [];
}

public sealed class FashionJobRequestDto
{
    public string Task { get; set; } = "";
    public string PersonAssetId { get; set; } = "";
    public string? GarmentAssetId { get; set; }
    public string? ScenePreset { get; set; }
    public string? SceneText { get; set; }
    public string? Color { get; set; }
    public string? ViewPreset { get; set; }
    public string? ExtraPrompt { get; set; }
    public int? Seed { get; set; }
    public int? Steps { get; set; }
}
