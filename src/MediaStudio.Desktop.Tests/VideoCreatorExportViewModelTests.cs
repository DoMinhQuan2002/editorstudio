using System.IO;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Tests;

public sealed class VideoCreatorExportViewModelTests
{
    [Fact]
    public async Task ExportRequiresExactDraftRevisionAndCompositionFingerprint()
    {
        using var files = new TemporaryFiles();
        var handoff = CreateHandoff(files.PreviewPath);
        var service = new FakeExportService(handoff) { Revision = handoff.DraftRevision + 1 };
        var vm = new VideoCreatorExportViewModel(service, new FakeUi(), handoff, () => { });

        await vm.LoadAsync();

        Assert.False(vm.CanExport);
        Assert.False(vm.IsPreviewSourceVerified);
        Assert.Contains("đổi ID, revision", vm.ErrorMessage);
        Assert.Empty(service.StartedRequests);
    }

    [Fact]
    public async Task PreviewWaitsForVerifiedSourceAndTracksOpenedPlayingAndFailedStates()
    {
        using var files = new TemporaryFiles();
        var handoff = CreateHandoff(files.PreviewPath);
        var vm = new VideoCreatorExportViewModel(new FakeExportService(handoff), new FakeUi(), handoff, () => { });

        await vm.LoadAsync();

        Assert.True(vm.IsPreviewSourceVerified);
        Assert.True(vm.IsPreviewLoading);
        Assert.False(vm.IsPreviewMediaOpened);
        vm.MarkPreviewMediaOpened(TimeSpan.FromSeconds(15));
        Assert.True(vm.IsPreviewSourceVerified);
        Assert.False(vm.IsPreviewLoading);
        Assert.True(vm.IsPreviewMediaOpened);
        Assert.False(vm.HasPreviewError);

        vm.SetIsPreviewPlaying(true);
        Assert.True(vm.IsPreviewPlaying);
        vm.SetPreviewPlaybackError("decoder failure");
        Assert.False(vm.IsPreviewSourceVerified);
        Assert.False(vm.IsPreviewMediaOpened);
        Assert.False(vm.IsPreviewPlaying);
        Assert.True(vm.HasPreviewError);
        Assert.Contains("decoder failure", vm.PreviewStatus);
    }

    [Fact]
    public async Task PreviewCannotAttachWhenTheVerifiedHandoffFileIsMissing()
    {
        using var files = new TemporaryFiles();
        var handoff = CreateHandoff(files.PreviewPath);
        File.Delete(files.PreviewPath);
        var vm = new VideoCreatorExportViewModel(new FakeExportService(handoff), new FakeUi(), handoff, () => { });

        await vm.LoadAsync();

        Assert.False(vm.IsPreviewSourceVerified);
        Assert.True(vm.HasPreviewError);
        Assert.Contains("Không tìm thấy video preview", vm.PreviewStatus);
    }

    [Fact]
    public async Task FilenameValidationRejectsWindowsNamesTraversalAndDuplicateExtension()
    {
        using var files = new TemporaryFiles();
        var handoff = CreateHandoff(files.PreviewPath);
        var vm = new VideoCreatorExportViewModel(new FakeExportService(handoff), new FakeUi(), handoff, () => { });
        await vm.LoadAsync();
        vm.OutputDirectory = files.DirectoryPath;

        vm.FileName = "CON";
        Assert.Contains("thiết bị dành riêng", vm.FileNameError);
        Assert.False(vm.CanExport);

        vm.FileName = "../escape";
        Assert.Contains("ký tự không hợp lệ", vm.FileNameError);

        vm.FileName = "Denim.mp4.mp4";
        Assert.Contains("lặp đuôi", vm.FileNameError);

        vm.FileName = "Denim Story.mp4";
        Assert.Empty(vm.FileNameError);
        Assert.EndsWith("Denim Story.mp4", vm.OutputFilePath);
        Assert.True(vm.CanExport);
    }

    [Fact]
    public async Task ExportAllowsSafeChildOutputFolderToBeCreatedByBackend()
    {
        using var files = new TemporaryFiles();
        var handoff = CreateHandoff(files.PreviewPath);
        var vm = new VideoCreatorExportViewModel(new FakeExportService(handoff), new FakeUi(), handoff, () => { });
        await vm.LoadAsync();
        var childDirectory = Path.Combine(files.DirectoryPath, "new export folder");

        vm.OutputDirectory = childDirectory;

        Assert.False(Directory.Exists(childDirectory));
        Assert.True(vm.CanExport);
    }

    [Fact]
    public async Task ExportPollsSameJobAndShowsSuccessOnlyForVerifiedExistingOutput()
    {
        using var files = new TemporaryFiles();
        var handoff = CreateHandoff(files.PreviewPath);
        var service = new FakeExportService(handoff);
        var ui = new FakeUi();
        var vm = new VideoCreatorExportViewModel(service, ui, handoff, () => { });
        await vm.LoadAsync();
        vm.OutputDirectory = files.DirectoryPath;
        vm.FileName = "Denim Story";

        await vm.ExportCommand.ExecuteAsync();

        Assert.Single(service.StartedRequests);
        Assert.Matches("^[a-f0-9]{32}$", service.StartedRequests[0].RequestId);
        Assert.Equal("Denim Story", service.StartedRequests[0].FileName);
        Assert.Equal("standard", service.StartedRequests[0].Quality);
        Assert.True(vm.IsSucceeded);
        Assert.Equal(100, vm.ProgressPercent);
        Assert.Equal("Xuất video thành công!", vm.Status);
        Assert.True(File.Exists(vm.ResultPath));

        vm.OpenVideoCommand.Execute(null);
        vm.OpenFolderCommand.Execute(null);
        Assert.Equal(vm.ResultPath, ui.OpenedFile);
        Assert.Equal(files.DirectoryPath, ui.OpenedFolder);
    }

    private static Screen6DraftHandoff CreateHandoff(string previewPath) => new(
        "a1111111111111111111111111111111", 3, "denim-story", "1.0.0",
        "/api/v1/video/projects/a1111111111111111111111111111111", "graph-fingerprint", previewPath);

    private sealed class FakeExportService(Screen6DraftHandoff handoff) : IVideoCreatorExportService
    {
        public int Revision { get; set; } = handoff.DraftRevision;
        public List<VideoCreatorExportRequestDto> StartedRequests { get; } = [];
        public string? ResultPath { get; private set; }

        public Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default) =>
            Task.FromResult(new VideoProjectDto
            {
                ProjectId = projectId, TemplateId = handoff.TemplateId, Title = "Denim Story",
                Revision = Revision, Width = 1080, Height = 1920, Fps = 30,
            });

        public Task<VideoCreatorExportCapabilitiesDto> GetCapabilitiesAsync(
            string projectId, CancellationToken cancellationToken = default) =>
            Task.FromResult(new VideoCreatorExportCapabilitiesDto
            {
                CanExport = true, DraftProjectId = projectId, DraftRevision = handoff.DraftRevision,
                TemplateId = handoff.TemplateId, TemplateVersion = handoff.TemplateVersion,
                CompositionFingerprint = handoff.CompositionFingerprint, CompositionReference = handoff.CompositionReference,
                MediaBindings = new Dictionary<string, string> { ["hero"] = "1".PadLeft(32, '1') },
                Width = 1080, Height = 1920, FrameRateNumerator = 30, FrameRateDenominator = 1,
                DurationTicks = 1_350_000, Timebase = 90_000, Qualities = ["standard", "high"],
                Format = "mp4", VideoCodec = "h264", SupportsCancel = true,
            });

        public Task<VideoRenderJobDto> StartExportAsync(
            string projectId, VideoCreatorExportRequestDto request, CancellationToken cancellationToken = default)
        {
            StartedRequests.Add(request);
            var outputDirectory = request.OutputDirectory;
            var path = Path.Combine(outputDirectory, request.FileName + ".mp4");
            File.WriteAllBytes(path, [0, 0, 0, 24, 0x66, 0x74, 0x79, 0x70, 1, 2, 3]);
            ResultPath = path;
            return Task.FromResult(new VideoRenderJobDto
            {
                JobId = "b1111111111111111111111111111111", ProjectId = projectId,
                State = "queued", Progress = 0, Stage = "Queued",
            });
        }

        public Task<VideoRenderJobDto> GetJobAsync(string jobId, CancellationToken cancellationToken = default) =>
            Task.FromResult(new VideoRenderJobDto
            {
                JobId = jobId, ProjectId = handoff.DraftProjectId, State = "succeeded", Progress = 100, Stage = "Done",
                ExportResult = new VideoExportResultDto
                {
                    OutputPath = ResultPath!, DurationMs = 15_000, Width = 1080, Height = 1920,
                    FrameRateNumerator = 30, FrameRateDenominator = 1, Format = "MP4", VideoCodec = "H.264",
                    SizeBytes = new FileInfo(ResultPath!).Length, FullDecodePassed = true,
                },
            });

        public Task CancelJobAsync(string jobId, CancellationToken cancellationToken = default) => Task.CompletedTask;
    }

    private sealed class FakeUi : IVideoCreatorExportUi
    {
        public bool ConfirmOverwriteResult { get; set; } = true;
        public string? OpenedFile { get; private set; }
        public string? OpenedFolder { get; private set; }
        public string? PickOutputFolder(string currentFolder) => currentFolder;
        public bool ConfirmOverwrite(string path) => ConfirmOverwriteResult;
        public void OpenFile(string path) => OpenedFile = path;
        public void OpenFolder(string path) => OpenedFolder = path;
    }

    private sealed class TemporaryFiles : IDisposable
    {
        public TemporaryFiles()
        {
            DirectoryPath = Path.Combine(Path.GetTempPath(), "ms-task37-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(DirectoryPath);
            PreviewPath = Path.Combine(DirectoryPath, "preview.mp4");
            File.WriteAllBytes(PreviewPath, [0, 0, 0, 24, 0x66, 0x74, 0x79, 0x70]);
        }
        public string DirectoryPath { get; }
        public string PreviewPath { get; }
        public void Dispose() => Directory.Delete(DirectoryPath, recursive: true);
    }
}
