namespace MediaStudio.Desktop.Services;

/// <summary>Renders photo story templates (image output, one image per page).</summary>
public interface IStoryTemplateService
{
    Task<StoryRenderResultDto> RenderAsync(string templateId, string version,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default);

    /// <summary>Render and save one page into the run folder <paramref name="runId"/>.</summary>
    Task<StoryRenderResultDto> RenderPageAsync(string templateId, string version, Dictionary<string, string> bindings,
        int page, string runId, CancellationToken cancellationToken = default);

    /// <summary>PNG of one page with the photos chosen so far; empty slots are numbered placeholders.</summary>
    Task<byte[]> RenderPagePreviewAsync(string templateId, int page, Dictionary<string, string> bindings,
        int width = 540, CancellationToken cancellationToken = default);
}

public sealed class StoryTemplateService(MediaStudioApiClient client) : IStoryTemplateService
{
    public Task<StoryRenderResultDto> RenderAsync(string templateId, string version,
        Dictionary<string, string> bindings, CancellationToken cancellationToken = default) =>
        client.RenderStoryTemplateAsync(templateId, version, bindings, "png", cancellationToken);

    public Task<StoryRenderResultDto> RenderPageAsync(string templateId, string version,
        Dictionary<string, string> bindings, int page, string runId, CancellationToken cancellationToken = default) =>
        client.RenderStoryPageAsync(templateId, version, bindings, page, runId, "png", cancellationToken);

    public Task<byte[]> RenderPagePreviewAsync(string templateId, int page, Dictionary<string, string> bindings,
        int width = 540, CancellationToken cancellationToken = default) =>
        client.RenderStoryPagePreviewAsync(templateId, page, bindings, width, cancellationToken);
}
