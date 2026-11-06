using System.Text.Json;
using System.IO;

namespace MediaStudio.Desktop.Services;

public interface ITemplateProcessingService
{
    Task<TemplateProcessingJobDto> StartAsync(
        string templateId, string templateVersion, string selectionSessionId,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default);
    Task<TemplateProcessingJobDto> GetAsync(string jobId, CancellationToken cancellationToken = default);
    Task VerifyHandoffAsync(TemplateProcessingJobDto job, string templateId, string templateVersion,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default);
}

public sealed class TemplateProcessingService(MediaStudioApiClient client) : ITemplateProcessingService
{
    public Task<TemplateProcessingJobDto> StartAsync(
        string templateId, string templateVersion, string selectionSessionId,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default) =>
        client.StartTemplateProcessingAsync(templateId, templateVersion, selectionSessionId, bindings, cancellationToken);

    public Task<TemplateProcessingJobDto> GetAsync(string jobId, CancellationToken cancellationToken = default) =>
        client.GetTemplateProcessingJobAsync(jobId, cancellationToken);

    public async Task VerifyHandoffAsync(TemplateProcessingJobDto job, string templateId, string templateVersion,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(job.DraftProjectId))
            throw new InvalidDataException("Backend báo thành công nhưng không trả mã bản nháp.");
        var project = await client.GetVideoProjectAsync(job.DraftProjectId, cancellationToken);
        if (project.ProjectId != job.DraftProjectId || project.TemplateId != templateId)
            throw new InvalidDataException("Project V2 không khớp mã bản nháp hoặc Template ID.");
        if (ReadMetadataString(project, "templateDefinitionVersion") != templateVersion)
            throw new InvalidDataException("Phiên bản Template Definition trong Project V2 không khớp.");
        var persistedBindings = ReadMetadataStringMap(project, "templateBindings");
        if (persistedBindings is null || persistedBindings.Count != bindings.Count
            || bindings.Any(item => !persistedBindings.TryGetValue(item.Key, out var value) || value != item.Value))
            throw new InvalidDataException("Media bindings trong Project V2 không khớp lựa chọn.");

        if (string.IsNullOrWhiteSpace(job.CompositionReference)
            || !job.CompositionReference.Contains($"/projects/{job.DraftProjectId}", StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(job.PreviewReference)
            || !job.PreviewReference.Contains($"/projects/{job.DraftProjectId}/preview/frame", StringComparison.Ordinal))
            throw new InvalidDataException("Composition hoặc preview reference không trỏ đến bản nháp này.");
        var preview = await client.RenderVideoCompositionPreviewAsync(project, 0, cancellationToken);
        if (preview.PngBytes.Length < 8
            || !preview.PngBytes.AsSpan(0, 8).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }))
            throw new InvalidDataException("Project V2 chưa thể dựng preview PNG.");
    }

    private static string? ReadMetadataString(VideoProjectDto project, string key)
    {
        if (!project.TemplateMetadata.TryGetValue(key, out var value) || value is not JsonElement element
            || element.ValueKind != JsonValueKind.String) return null;
        return element.GetString();
    }

    private static Dictionary<string, string>? ReadMetadataStringMap(VideoProjectDto project, string key)
    {
        if (!project.TemplateMetadata.TryGetValue(key, out var value) || value is not JsonElement element
            || element.ValueKind != JsonValueKind.Object) return null;
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var item in element.EnumerateObject())
        {
            if (item.Value.ValueKind != JsonValueKind.String || !result.TryAdd(item.Name, item.Value.GetString() ?? ""))
                return null;
        }
        return result;
    }
}
