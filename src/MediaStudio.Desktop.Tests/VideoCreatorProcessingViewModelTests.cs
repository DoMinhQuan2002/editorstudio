using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MediaStudio.Desktop.Tests;

public sealed class VideoCreatorProcessingViewModelTests
{
    [Fact]
    public async Task JobPollingUsesBackendStagesAndRequiresPreviewBeforeSuccess()
    {
        var service = new FakeProcessingService();
        var vm = new VideoCreatorProcessingViewModel(
            service, new MediaSelectionSessionRequest("template-id", "a".PadLeft(32, 'a')),
            "v1", new Dictionary<string, string> { ["hero"] = "b".PadLeft(32, 'b') }, () => { });

        await vm.StartAsync();
        Assert.Equal("job-id", vm.JobId);
        Assert.Null(vm.ProgressPercent);
        Assert.Equal("RUNNING", vm.JobStatus);
        Assert.True(vm.IsProcessingActive);
        Assert.Equal("COMPLETED", vm.Stages[0].Status);
        Assert.Equal("RUNNING", vm.Stages[1].Status);

        var deadline = DateTime.UtcNow.AddSeconds(3);
        while (!vm.IsSucceeded && DateTime.UtcNow < deadline) await Task.Delay(40);

        Assert.True(vm.IsSucceeded);
        Assert.Equal("SUCCEEDED", vm.JobStatus);
        Assert.Equal(100, vm.ProgressPercent);
        Assert.Equal("draft-id", vm.DraftProjectId);
        Assert.Contains("draft-id", vm.HandoffMessage);
        Assert.False(vm.IsProcessingActive);
    }

    [Fact]
    public async Task SuccessfulProcessingOpensScreenFiveOnlyAfterHandoffVerification()
    {
        var service = new FakeProcessingService();
        var opened = new TaskCompletionSource<VideoCreatorProcessingViewModel>(TaskCreationOptions.RunContinuationsAsynchronously);
        var vm = new VideoCreatorProcessingViewModel(
            service, new MediaSelectionSessionRequest("template-id", "7".PadLeft(32, '7')),
            "v1", new Dictionary<string, string> { ["hero"] = "8".PadLeft(32, '8') }, () => { },
            preview =>
            {
                opened.SetResult(preview);
                return Task.CompletedTask;
            });

        await vm.StartAsync();
        var result = await opened.Task.WaitAsync(TimeSpan.FromSeconds(4));

        Assert.True(result.IsSucceeded);
        Assert.Equal("draft-id", result.DraftProjectId);
        Assert.True(result.OpenDraftPreviewCommand.CanExecute(null));
    }

    [Fact]
    public async Task SuccessWithoutDraftOrPreviewIsRejected()
    {
        var service = new FakeProcessingService { ReturnIncompleteSuccess = true };
        var vm = new VideoCreatorProcessingViewModel(
            service, new MediaSelectionSessionRequest("template-id", "c".PadLeft(32, 'c')),
            "v1", new Dictionary<string, string> { ["hero"] = "d".PadLeft(32, 'd') }, () => { });

        await vm.StartAsync();

        Assert.False(vm.IsSucceeded);
        Assert.True(vm.IsFailed);
        Assert.Equal("INVALID_HANDOFF", vm.ErrorCode);
        Assert.False(vm.IsProcessingActive);
    }

    [Fact]
    public async Task FailedBackendJobCanBeRetriedWithoutLosingTheSelectionSession()
    {
        var service = new FakeProcessingService { FailFirstStart = true };
        var request = new MediaSelectionSessionRequest("template-id", "e".PadLeft(32, 'e'));
        var vm = new VideoCreatorProcessingViewModel(
            service, request, "v1", new Dictionary<string, string> { ["hero"] = "f".PadLeft(32, 'f') }, () => { });

        await vm.StartAsync();
        Assert.True(vm.IsFailed);
        Assert.Equal("PREVIEW_FAILED", vm.ErrorCode);
        Assert.False(vm.IsProcessingActive);
        Assert.True(vm.RetryCommand.CanExecute(null));

        await vm.RetryCommand.ExecuteAsync();
        await WaitUntilAsync(() => vm.IsSucceeded);

        Assert.Equal(2, service.StartCount);
        Assert.Equal("job-id-2", vm.JobId);
        Assert.Equal(request.SelectionSessionId, service.LastSelectionSessionId);
        Assert.Equal(new[] { "job-id-2" }, service.PolledJobIds);
        Assert.True(vm.IsSucceeded);
    }

    [Fact]
    public async Task StartRequestFailureCanBeRetried()
    {
        var service = new FakeProcessingService { ThrowFirstStart = true };
        var vm = new VideoCreatorProcessingViewModel(
            service, new MediaSelectionSessionRequest("template-id", "5".PadLeft(32, '5')),
            "v1", new Dictionary<string, string> { ["hero"] = "6".PadLeft(32, '6') }, () => { });

        await vm.StartAsync();
        Assert.True(vm.IsFailed);
        Assert.Equal("START_FAILED", vm.ErrorCode);
        Assert.True(vm.RetryCommand.CanExecute(null));

        await vm.RetryCommand.ExecuteAsync();
        await WaitUntilAsync(() => vm.IsSucceeded);

        Assert.Equal(2, service.StartCount);
        Assert.Equal("job-id-2", vm.JobId);
        Assert.True(vm.IsSucceeded);
    }

    [Fact]
    public async Task PollDisconnectIsShownAndRecoveryKeepsPollingTheSameJob()
    {
        var service = new FakeProcessingService { DisconnectFirstPoll = true };
        var vm = new VideoCreatorProcessingViewModel(
            service, new MediaSelectionSessionRequest("template-id", "1".PadLeft(32, '1')),
            "v1", new Dictionary<string, string> { ["hero"] = "2".PadLeft(32, '2') }, () => { });

        await vm.StartAsync();
        await service.FirstPollDisconnected.Task.WaitAsync(TimeSpan.FromSeconds(3));
        await WaitUntilAsync(() => !string.IsNullOrWhiteSpace(vm.ConnectionMessage));
        Assert.False(vm.IsSucceeded);

        await WaitUntilAsync(() => vm.IsSucceeded, TimeSpan.FromSeconds(6));

        Assert.Equal(1, service.StartCount);
        Assert.Equal("job-id", vm.JobId);
        Assert.All(service.PolledJobIds, id => Assert.Equal("job-id", id));
        Assert.Null(vm.ConnectionMessage);
    }

    [Fact]
    public async Task MismatchedBackendBindingFingerprintCannotSucceed()
    {
        var service = new FakeProcessingService { ReturnIdentityMismatch = true };
        var vm = new VideoCreatorProcessingViewModel(
            service, new MediaSelectionSessionRequest("template-id", "3".PadLeft(32, '3')),
            "v1", new Dictionary<string, string> { ["hero"] = "4".PadLeft(32, '4') }, () => { });

        await vm.StartAsync();

        Assert.False(vm.IsSucceeded);
        Assert.True(vm.IsFailed);
        Assert.Equal("JOB_IDENTITY_MISMATCH", vm.ErrorCode);
        Assert.Empty(service.PolledJobIds);
    }

    private static async Task WaitUntilAsync(Func<bool> predicate, TimeSpan? timeout = null)
    {
        var deadline = DateTime.UtcNow + (timeout ?? TimeSpan.FromSeconds(3));
        while (!predicate() && DateTime.UtcNow < deadline) await Task.Delay(40);
        Assert.True(predicate(), "Expected the processing view model to reach the requested state.");
    }

    private sealed class FakeProcessingService : ITemplateProcessingService
    {
        public bool ReturnIncompleteSuccess { get; init; }
        public bool FailFirstStart { get; init; }
        public bool ThrowFirstStart { get; init; }
        public bool DisconnectFirstPoll { get; init; }
        public bool ReturnIdentityMismatch { get; init; }
        public int StartCount { get; private set; }
        public List<string> PolledJobIds { get; } = [];
        public string? LastSelectionSessionId { get; private set; }
        public TaskCompletionSource<bool> FirstPollDisconnected { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private string? _lastTemplateId;
        private string? _lastTemplateVersion;
        private Dictionary<string, string> _lastBindings = [];

        public Task<TemplateProcessingJobDto> StartAsync(string templateId, string templateVersion,
            string selectionSessionId, Dictionary<string, string> bindings, CancellationToken cancellationToken = default)
        {
            StartCount++;
            LastSelectionSessionId = selectionSessionId;
            _lastTemplateId = templateId;
            _lastTemplateVersion = templateVersion;
            _lastBindings = new Dictionary<string, string>(bindings, StringComparer.Ordinal);
            if (ThrowFirstStart && StartCount == 1) throw new HttpRequestException("Simulated start failure.");
            if (ReturnIncompleteSuccess)
                return Task.FromResult(Succeeded(includePreview: false, templateId, templateVersion, selectionSessionId, bindings));
            var jobId = $"job-id{(StartCount == 1 ? "" : $"-{StartCount}")}";
            if (FailFirstStart && StartCount == 1)
                return Task.FromResult(Failed(templateId, templateVersion, selectionSessionId, bindings, jobId));
            var job = Running(templateId, templateVersion, selectionSessionId, bindings, jobId);
            if (ReturnIdentityMismatch) job.BindingFingerprint = new string('0', 64);
            return Task.FromResult(job);
        }

        public Task<TemplateProcessingJobDto> GetAsync(string jobId, CancellationToken cancellationToken = default) =>
            GetCoreAsync(jobId);

        private Task<TemplateProcessingJobDto> GetCoreAsync(string jobId)
        {
            PolledJobIds.Add(jobId);
            if (DisconnectFirstPoll && PolledJobIds.Count == 1)
            {
                FirstPollDisconnected.TrySetResult(true);
                throw new HttpRequestException("Simulated backend disconnect.");
            }
            return Task.FromResult(Succeeded(includePreview: true, _lastTemplateId!, _lastTemplateVersion!,
                LastSelectionSessionId!, _lastBindings, jobId));
        }

        public Task VerifyHandoffAsync(TemplateProcessingJobDto job, string templateId, string templateVersion,
            Dictionary<string, string> bindings, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(job.PreviewReference))
                throw new InvalidDataException("No preview reference.");
            return Task.CompletedTask;
        }

        private static TemplateProcessingJobDto Running(string templateId, string templateVersion,
            string selectionSessionId, Dictionary<string, string> bindings, string jobId = "job-id") => new()
        {
            JobId = jobId, JobStatus = "RUNNING", TemplateId = templateId, TemplateVersion = templateVersion,
            SelectionSessionId = selectionSessionId, BindingFingerprint = Fingerprint(templateId, templateVersion, bindings),
            ProgressPercent = null,
            CurrentStage = "apply_layout", Stages =
            [
                new() { StageId = "analyze_media", Name = "Phân tích media", Status = "COMPLETED" },
                new() { StageId = "apply_layout", Name = "Áp dụng bố cục mẫu", Status = "RUNNING" },
            ]
        };

        private static TemplateProcessingJobDto Succeeded(bool includePreview, string templateId,
            string templateVersion, string selectionSessionId, Dictionary<string, string> bindings, string jobId = "job-id") => new()
        {
            JobId = jobId, JobStatus = "SUCCEEDED", ProgressPercent = 100,
            TemplateId = templateId, TemplateVersion = templateVersion, SelectionSessionId = selectionSessionId,
            BindingFingerprint = Fingerprint(templateId, templateVersion, bindings),
            DraftProjectId = "draft-id", CompositionReference = "/api/v1/video/projects/draft-id",
            PreviewReference = includePreview ? "/api/v1/video/projects/draft-id/preview/frame?timestamp_ticks=0" : null,
            Stages =
            [
                new() { StageId = "analyze_media", Name = "Phân tích media", Status = "COMPLETED" },
                new() { StageId = "apply_layout", Name = "Áp dụng bố cục mẫu", Status = "COMPLETED" },
                new() { StageId = "build_composition", Name = "Tạo chuyển cảnh và hiệu ứng", Status = "COMPLETED" },
                new() { StageId = "sync_audio", Name = "Đồng bộ nhạc nền", Status = "SKIPPED" },
                new() { StageId = "prepare_preview", Name = "Hoàn tất...", Status = "COMPLETED" },
            ]
        };

        private static TemplateProcessingJobDto Failed(string templateId, string templateVersion,
            string selectionSessionId, Dictionary<string, string> bindings, string jobId) => new()
        {
            JobId = jobId, JobStatus = "FAILED", ErrorCode = "PREVIEW_FAILED", ErrorMessage = "Preview failed.",
            TemplateId = templateId, TemplateVersion = templateVersion, SelectionSessionId = selectionSessionId,
            BindingFingerprint = Fingerprint(templateId, templateVersion, bindings),
            Stages = [new() { StageId = "prepare_preview", Name = "Hoàn tất...", Status = "FAILED" }]
        };

        private static string Fingerprint(string templateId, string templateVersion, Dictionary<string, string> bindings)
        {
            var sorted = new SortedDictionary<string, string>(bindings, StringComparer.Ordinal);
            var canonical = JsonSerializer.Serialize(new { templateId, templateVersion, bindings = sorted });
            return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
        }
    }
}
