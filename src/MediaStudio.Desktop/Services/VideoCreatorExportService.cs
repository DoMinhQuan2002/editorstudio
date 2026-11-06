using System.Diagnostics;
using System.IO;
using System.Windows;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.Services;

public interface IVideoCreatorExportService
{
    Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default);
    Task<VideoCreatorExportCapabilitiesDto> GetCapabilitiesAsync(string projectId, CancellationToken cancellationToken = default);
    Task<VideoRenderJobDto> StartExportAsync(
        string projectId, VideoCreatorExportRequestDto request, CancellationToken cancellationToken = default);
    Task<VideoRenderJobDto> GetJobAsync(string jobId, CancellationToken cancellationToken = default);
    Task CancelJobAsync(string jobId, CancellationToken cancellationToken = default);
}

public sealed class MediaStudioVideoCreatorExportService(MediaStudioApiClient client) : IVideoCreatorExportService
{
    public Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default) =>
        client.GetVideoProjectAsync(projectId, cancellationToken);

    public Task<VideoCreatorExportCapabilitiesDto> GetCapabilitiesAsync(
        string projectId, CancellationToken cancellationToken = default) =>
        client.GetVideoCreatorExportCapabilitiesAsync(projectId, cancellationToken);

    public Task<VideoRenderJobDto> StartExportAsync(
        string projectId, VideoCreatorExportRequestDto request, CancellationToken cancellationToken = default) =>
        client.StartVideoCreatorExportAsync(projectId, request, cancellationToken);

    public Task<VideoRenderJobDto> GetJobAsync(string jobId, CancellationToken cancellationToken = default) =>
        client.GetVideoRenderJobAsync(jobId, cancellationToken);

    public Task CancelJobAsync(string jobId, CancellationToken cancellationToken = default) =>
        client.CancelVideoRenderJobAsync(jobId, cancellationToken);
}

public interface IVideoCreatorExportUi
{
    string? PickOutputFolder(string currentFolder);
    bool ConfirmOverwrite(string path);
    void OpenFile(string path);
    void OpenFolder(string path);
}

public sealed class WpfVideoCreatorExportUi : IVideoCreatorExportUi
{
    public string? PickOutputFolder(string currentFolder)
    {
        var dialog = new Microsoft.Win32.OpenFolderDialog
        {
            Title = "Chọn thư mục lưu video",
            InitialDirectory = Directory.Exists(currentFolder) ? currentFolder : Environment.GetFolderPath(Environment.SpecialFolder.MyVideos),
            Multiselect = false,
        };
        return dialog.ShowDialog() == true ? dialog.FolderName : null;
    }

    public bool ConfirmOverwrite(string path) => MessageBox.Show(
        $"File này đã tồn tại:\n{path}\n\nBạn muốn thay thế file sau khi video mới được xác minh?",
        "Xác nhận ghi đè", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes;

    public void OpenFile(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });

    public void OpenFolder(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
}
