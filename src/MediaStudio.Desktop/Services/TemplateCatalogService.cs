namespace MediaStudio.Desktop.Services;

/// <summary>Application boundary for the backend's real video-template catalog.</summary>
public sealed class TemplateCatalogService(MediaStudioApiClient apiClient)
{
    private readonly MediaStudioApiClient _apiClient = apiClient;

    public Task<IReadOnlyList<VideoTemplateDto>> GetTemplatesAsync(CancellationToken cancellationToken = default) =>
        _apiClient.GetVideoTemplatesAsync(cancellationToken);
}
