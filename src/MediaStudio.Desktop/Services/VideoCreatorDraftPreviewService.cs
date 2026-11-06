using System.IO;

namespace MediaStudio.Desktop.Services;

public interface IVideoCreatorDraftPreviewService
{
    Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<VideoProjectDto>> GetProjectsAsync(CancellationToken cancellationToken = default);
    Task<VideoProjectDto> SaveProjectAsync(VideoProjectDto project, CancellationToken cancellationToken = default);
    Task<VideoCompositionPreviewFrame> RenderFrameAsync(
        VideoProjectDto project, long timestampTicks, CancellationToken cancellationToken = default);
    Task<string> RenderPlaybackPreviewAsync(VideoProjectDto project, CancellationToken cancellationToken = default);
    Task<VideoOverlayEditLayerDto> GetOverlayEditLayerAsync(
        VideoProjectDto project, string clipId, long timestampTicks, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException("Dịch vụ preview này không hỗ trợ chỉnh ảnh trực tiếp.");
}

public sealed class VideoCreatorDraftPreviewService : IVideoCreatorDraftPreviewService
{
    private readonly MediaStudioApiClient _client;
    private readonly string _cacheDirectory = Path.Combine(
        Path.GetTempPath(), "MediaStudio", "DraftPreviewCache");

    public VideoCreatorDraftPreviewService(MediaStudioApiClient client)
    {
        _client = client;
        Directory.CreateDirectory(_cacheDirectory);
        foreach (var stalePreview in Directory.EnumerateFiles(_cacheDirectory, "*.mp4"))
        {
            try { File.Delete(stalePreview); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    public Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default) =>
        _client.GetVideoProjectAsync(projectId, cancellationToken);

    public Task<IReadOnlyList<VideoProjectDto>> GetProjectsAsync(CancellationToken cancellationToken = default) =>
        _client.GetVideoProjectsAsync(cancellationToken);

    public Task<VideoProjectDto> SaveProjectAsync(VideoProjectDto project, CancellationToken cancellationToken = default) =>
        _client.SaveVideoProjectAsync(project, cancellationToken);

    public Task<VideoCompositionPreviewFrame> RenderFrameAsync(
        VideoProjectDto project, long timestampTicks, CancellationToken cancellationToken = default) =>
        _client.RenderVideoCompositionPreviewAsync(project, timestampTicks, cancellationToken);

    public Task<VideoOverlayEditLayerDto> GetOverlayEditLayerAsync(
        VideoProjectDto project, string clipId, long timestampTicks, CancellationToken cancellationToken = default) =>
        _client.GetVideoOverlayEditLayerAsync(project, clipId, timestampTicks, cancellationToken);

    public async Task<string> RenderPlaybackPreviewAsync(
        VideoProjectDto project, CancellationToken cancellationToken = default)
    {
        var preview = await _client.RenderVideoCompositionPreviewVideoAsync(project, cancellationToken);
        if (preview.ProjectRevision != project.Revision)
            throw new InvalidDataException("Video preview thuộc revision khác với bản nháp đang mở.");
        var path = Path.Combine(_cacheDirectory, $"{project.ProjectId}_r{project.Revision}_{Guid.NewGuid():N}.mp4");
        await File.WriteAllBytesAsync(path, preview.Mp4Bytes, cancellationToken);
        return path;
    }
}
