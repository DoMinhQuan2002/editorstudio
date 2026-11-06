using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public sealed class VideoCreatorProcessingViewModel : ObservableObject
{
    private static readonly TimeSpan StartRequestTimeout = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan PollRequestTimeout = TimeSpan.FromSeconds(5);
    // Background removal runs one segmentation per overlay image and downloads
    // its model on first use, so a healthy run can legitimately outlast a flat
    // wall-clock budget. Give up when the backend stops reporting new progress,
    // and keep a generous absolute cap so a wedged job still ends.
    private static readonly TimeSpan ProcessingStallTimeout = TimeSpan.FromMinutes(10);
    private static readonly TimeSpan ProcessingPollTimeout = TimeSpan.FromMinutes(40);
    private readonly ITemplateProcessingService _service;
    private readonly MediaSelectionSessionRequest _request;
    private readonly string _templateVersion;
    private readonly Dictionary<string, string> _bindings;
    private readonly string _expectedBindingFingerprint;
    private readonly Func<VideoCreatorProcessingViewModel, Task>? _openDraftPreview;
    private bool _isBusy;
    private bool _isPolling;
    private bool _isSucceeded;
    private bool _isFailed;
    private string _jobStatus = "QUEUED";
    private string? _jobId;
    private int? _progressPercent;
    private string? _currentStage;
    private string? _errorCode;
    private string? _errorMessage;
    private string? _draftProjectId;
    private string? _compositionReference;
    private string? _previewReference;
    private string? _connectionMessage;

    public VideoCreatorProcessingViewModel(
        ITemplateProcessingService service,
        MediaSelectionSessionRequest request,
        string templateVersion,
        Dictionary<string, string> bindings,
        Action back,
        Func<VideoCreatorProcessingViewModel, Task>? openDraftPreview = null)
    {
        _service = service;
        _request = request;
        _templateVersion = templateVersion;
        _bindings = new Dictionary<string, string>(bindings, StringComparer.Ordinal);
        _openDraftPreview = openDraftPreview;
        _expectedBindingFingerprint = ComputeBindingFingerprint(request.TemplateId, templateVersion, _bindings);
        BackCommand = new RelayCommand(_ => back());
        RetryCommand = new AsyncRelayCommand(RetryAsync, _ => CanRetry);
        OpenDraftPreviewCommand = new AsyncRelayCommand(OpenDraftPreviewAsync,
            _ => IsSucceeded && _openDraftPreview is not null);
        Stages = new ObservableCollection<ProcessingStageViewModel>(
        [
            new("analyze_media", "Phân tích media"),
            new("apply_layout", "Áp dụng bố cục mẫu"),
            new("build_composition", "Tạo chuyển cảnh và hiệu ứng"),
            new("sync_audio", "Đồng bộ nhạc nền"),
            new("prepare_preview", "Hoàn tất..."),
        ]);
    }

    public ObservableCollection<ProcessingStageViewModel> Stages { get; }
    public RelayCommand BackCommand { get; }
    public AsyncRelayCommand RetryCommand { get; }
    public AsyncRelayCommand OpenDraftPreviewCommand { get; }
    public string JobStatus
    {
        get => _jobStatus;
        private set
        {
            if (SetProperty(ref _jobStatus, value)) OnPropertyChanged(nameof(IsProcessingActive));
        }
    }
    public string? JobId { get => _jobId; private set => SetProperty(ref _jobId, value); }
    public string TemplateId => _request.TemplateId;
    public string TemplateVersion => _templateVersion;
    public int? ProgressPercent { get => _progressPercent; private set { if (SetProperty(ref _progressPercent, value)) OnPropertyChanged(nameof(ProgressLabel)); } }
    public string ProgressLabel => ProgressPercent is int value ? $"{value}%" : "";
    public string? CurrentStage { get => _currentStage; private set => SetProperty(ref _currentStage, value); }
    public string? ErrorCode { get => _errorCode; private set => SetProperty(ref _errorCode, value); }
    public string? ErrorMessage { get => _errorMessage; private set => SetProperty(ref _errorMessage, value); }
    public string? DraftProjectId { get => _draftProjectId; private set => SetProperty(ref _draftProjectId, value); }
    public string? CompositionReference { get => _compositionReference; private set => SetProperty(ref _compositionReference, value); }
    public string? PreviewReference { get => _previewReference; private set => SetProperty(ref _previewReference, value); }
    public string? ConnectionMessage { get => _connectionMessage; private set => SetProperty(ref _connectionMessage, value); }
    public bool IsBusy { get => _isBusy; private set { if (SetProperty(ref _isBusy, value)) RetryCommand?.NotifyCanExecuteChanged(); } }
    public bool IsSucceeded
    {
        get => _isSucceeded;
        private set
        {
            if (SetProperty(ref _isSucceeded, value))
            {
                OnPropertyChanged(nameof(Heading));
                OnPropertyChanged(nameof(IsProcessingActive));
                OpenDraftPreviewCommand?.NotifyCanExecuteChanged();
            }
        }
    }
    public bool IsFailed
    {
        get => _isFailed;
        private set
        {
            if (SetProperty(ref _isFailed, value))
            {
                OnPropertyChanged(nameof(Heading));
                OnPropertyChanged(nameof(IsProcessingActive));
            }
        }
    }
    public bool IsPolling
    {
        get => _isPolling;
        private set
        {
            if (!SetProperty(ref _isPolling, value)) return;
            OnPropertyChanged(nameof(CanRetry));
            RetryCommand?.NotifyCanExecuteChanged();
        }
    }
    public bool CanRetry => !IsBusy && !IsPolling && (!IsFailed || ErrorCode is "START_FAILED" or "PREVIEW_FAILED" or "PREVIEW_UNAVAILABLE" or "PROCESSING_FAILED" or "PROCESSING_TIMEOUT" or "PROCESSING_POLL_TIMEOUT")
        && (IsFailed || !string.IsNullOrWhiteSpace(ErrorMessage));
    public bool IsProcessingActive => !IsSucceeded && !IsFailed && (JobStatus is "QUEUED" or "RUNNING");
    public string Heading => IsFailed ? "Chưa thể áp dụng mẫu" : IsSucceeded ? "Đã chuẩn bị bản nháp" : "Đang áp dụng mẫu...";
    public string Description => IsFailed
        ? "Hệ thống chưa hoàn tất xử lý. Media gốc và lựa chọn của bạn vẫn được giữ lại."
        : IsSucceeded
            ? "Bản nháp Project V2 đã được lưu và có thể dựng preview từ Composition Graph."
            : "Hệ thống đang tự động sắp xếp media, áp dụng bố cục, chuyển cảnh và hiệu ứng theo mẫu của bạn.";
    public string HandoffMessage => IsSucceeded
        ? $"Bản nháp Project V2 đã xác minh · {DraftProjectId}."
        : "";

    public async Task StartAsync()
    {
        if (IsBusy || IsSucceeded) return;
        IsBusy = true;
        ErrorCode = null;
        ErrorMessage = null;
        ConnectionMessage = null;
        JobStatus = "QUEUED";
        IsFailed = false;
        try
        {
            var job = await StartWithTimeoutAsync();
            await ApplyAsync(job);
            if (!IsTerminal(job.JobStatus)) _ = PollAsync(job.JobId);
        }
        catch (Exception error)
        {
            IsFailed = true;
            JobStatus = "FAILED";
            ErrorCode = "START_FAILED";
            ErrorMessage = error.Message;
            OnPropertyChanged(nameof(CanRetry));
            OnPropertyChanged(nameof(Description));
            RetryCommand.NotifyCanExecuteChanged();
        }
        finally { IsBusy = false; }
    }

    private async Task RetryAsync()
    {
        if (IsBusy) return;
        if (!string.IsNullOrWhiteSpace(JobId))
        {
            // A failed backend job is terminal. Re-submit the same session/bindings
            // without pinning the next response to the old job ID.
            JobId = null;
            DraftProjectId = null;
            CompositionReference = null;
            PreviewReference = null;
            CurrentStage = null;
            IsFailed = false;
            IsSucceeded = false;
            JobStatus = "RUNNING";
            ProgressPercent = null;
            ErrorCode = null;
            ErrorMessage = null;
            foreach (var stage in Stages) stage.Reset();
            IsBusy = true;
            try
            {
                var job = await StartWithTimeoutAsync();
                await ApplyAsync(job);
                if (!IsTerminal(job.JobStatus)) _ = PollAsync(job.JobId);
            }
            catch (Exception error)
            {
                IsFailed = true;
                JobStatus = "FAILED";
                ErrorCode = "START_FAILED";
                ErrorMessage = error.Message;
                OnPropertyChanged(nameof(CanRetry));
                OnPropertyChanged(nameof(Description));
                RetryCommand.NotifyCanExecuteChanged();
            }
            finally { IsBusy = false; }
            return;
        }
        await StartAsync();
    }

    private async Task PollAsync(string jobId)
    {
        if (IsPolling) return;
        IsPolling = true;
        var pollingTimer = Stopwatch.StartNew();
        var stallTimer = Stopwatch.StartNew();
        var lastProgressSignature = string.Empty;
        var retryDelay = TimeSpan.FromMilliseconds(700);
        try
        {
            while (!IsTerminal(JobStatus))
            {
                var stalled = stallTimer.Elapsed >= ProcessingStallTimeout;
                if (stalled || pollingTimer.Elapsed >= ProcessingPollTimeout)
                {
                    IsFailed = true;
                    JobStatus = "FAILED";
                    ErrorCode = "PROCESSING_POLL_TIMEOUT";
                    ErrorMessage = stalled
                        ? $"Tác vụ không báo tiến độ mới trong {ProcessingStallTimeout.TotalMinutes:0} phút. Hãy thử lại; lựa chọn media vẫn được giữ."
                        : $"Không nhận được trạng thái hoàn tất trong {ProcessingPollTimeout.TotalMinutes:0} phút. Hãy thử lại; lựa chọn media vẫn được giữ.";
                    OnPropertyChanged(nameof(Description));
                    OnPropertyChanged(nameof(CanRetry));
                    break;
                }
                await Task.Delay(retryDelay);
                using var requestTimeout = new CancellationTokenSource(PollRequestTimeout);
                try
                {
                    var job = await _service.GetAsync(jobId, requestTimeout.Token);
                    await ApplyAsync(job);
                    var progressSignature = BuildProgressSignature(job);
                    if (!string.Equals(progressSignature, lastProgressSignature, StringComparison.Ordinal))
                    {
                        lastProgressSignature = progressSignature;
                        stallTimer.Restart();
                    }
                    ConnectionMessage = null;
                    retryDelay = TimeSpan.FromMilliseconds(700);
                }
                catch (OperationCanceledException) when (requestTimeout.IsCancellationRequested)
                {
                    ConnectionMessage = "Yêu cầu kiểm tra tiến độ vượt quá 5 giây. Đang thử kết nối lại.";
                    OnPropertyChanged(nameof(Description));
                    retryDelay = TimeSpan.FromSeconds(2);
                }
                catch (Exception error)
                {
                    ConnectionMessage = $"Mất kết nối khi theo dõi tác vụ. Đang thử kết nối lại: {error.Message}";
                    OnPropertyChanged(nameof(Description));
                    retryDelay = TimeSpan.FromSeconds(2);
                }
            }
        }
        finally { IsPolling = false; }
    }

    private static string BuildProgressSignature(TemplateProcessingJobDto job)
    {
        // Anything the backend newly reports counts as progress. The cutout stage
        // rewrites its message once per overlay image, so a run that is working
        // keeps resetting the stall timer even while one slow stage holds. The
        // job's UpdatedAt is left out on purpose: were the backend to touch it on
        // every read, the stall timer could never fire.
        var stages = string.Join("|", job.Stages.Select(stage => $"{stage.StageId}:{stage.Status}:{stage.Message}"));
        return $"{job.JobStatus}|{job.CurrentStage}|{job.ProgressPercent}|{stages}";
    }

    private async Task<TemplateProcessingJobDto> StartWithTimeoutAsync()
    {
        using var requestTimeout = new CancellationTokenSource(StartRequestTimeout);
        try
        {
            return await _service.StartAsync(
                _request.TemplateId, _templateVersion, _request.SelectionSessionId, _bindings, requestTimeout.Token);
        }
        catch (OperationCanceledException) when (requestTimeout.IsCancellationRequested)
        {
            throw new TimeoutException("Gửi yêu cầu xử lý vượt quá 15 giây. Bạn có thể thử lại.");
        }
    }

    private async Task ApplyAsync(TemplateProcessingJobDto job)
    {
        var identityError = ValidateJobIdentity(job);
        if (identityError is not null)
        {
            Reject("JOB_IDENTITY_MISMATCH", identityError);
            return;
        }
        JobId = string.IsNullOrWhiteSpace(job.JobId) ? JobId : job.JobId;
        JobStatus = string.IsNullOrWhiteSpace(job.JobStatus) ? JobStatus : job.JobStatus.ToUpperInvariant();
        CurrentStage = job.CurrentStage;
        ProgressPercent = job.ProgressPercent;
        ErrorCode = job.ErrorCode;
        ErrorMessage = job.ErrorMessage ?? job.Error;
        DraftProjectId = job.DraftProjectId;
        CompositionReference = job.CompositionReference;
        PreviewReference = job.PreviewReference;
        foreach (var stage in Stages)
        {
            var update = job.Stages.FirstOrDefault(item => item.StageId == stage.StageId);
            if (update is not null) stage.Apply(update);
        }
        IsSucceeded = false;
        IsFailed = JobStatus is "FAILED" or "CANCELLED";
        if (JobStatus == "SUCCEEDED")
        {
            var previewStageCompleted = Stages.Any(stage => stage.StageId == "prepare_preview" && stage.Status == "COMPLETED");
            if (string.IsNullOrWhiteSpace(DraftProjectId) || !previewStageCompleted)
            {
                Reject("INVALID_HANDOFF", "Backend báo thành công nhưng chưa trả đủ Project V2 hoặc preview hợp lệ.");
                return;
            }
            try
            {
                await _service.VerifyHandoffAsync(job, _request.TemplateId, _templateVersion, _bindings);
                IsSucceeded = true;
                IsFailed = false;
            }
            catch (Exception error)
            {
                Reject("INVALID_HANDOFF", $"Không thể xác nhận Project V2 và preview: {error.Message}");
                return;
            }
        }
        OnPropertyChanged(nameof(Description));
        OnPropertyChanged(nameof(HandoffMessage));
        OnPropertyChanged(nameof(CanRetry));
        RetryCommand.NotifyCanExecuteChanged();
        if (IsSucceeded && _openDraftPreview is not null) await _openDraftPreview(this);
    }

    private Task OpenDraftPreviewAsync() => _openDraftPreview?.Invoke(this) ?? Task.CompletedTask;

    private string? ValidateJobIdentity(TemplateProcessingJobDto job)
    {
        if (string.IsNullOrWhiteSpace(job.JobId)) return "Backend không trả Job ID.";
        if (!string.IsNullOrWhiteSpace(JobId) && !string.Equals(JobId, job.JobId, StringComparison.Ordinal))
            return "Backend trả Job ID khác tác vụ đang theo dõi.";
        if (job.TemplateId != _request.TemplateId || job.TemplateVersion != _templateVersion
            || job.SelectionSessionId != _request.SelectionSessionId
            || job.BindingFingerprint != _expectedBindingFingerprint)
            return "Job template, version, selection session hoặc binding fingerprint không khớp.";
        return null;
    }

    private void Reject(string code, string message)
    {
        IsSucceeded = false;
        IsFailed = true;
        JobStatus = "FAILED";
        ErrorCode = code;
        ErrorMessage = message;
        OnPropertyChanged(nameof(Description));
        OnPropertyChanged(nameof(CanRetry));
        RetryCommand.NotifyCanExecuteChanged();
    }

    private static string ComputeBindingFingerprint(
        string templateId, string templateVersion, IReadOnlyDictionary<string, string> bindings)
    {
        var sortedBindings = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var binding in bindings) sortedBindings.Add(binding.Key, binding.Value);
        var canonical = JsonSerializer.Serialize(new { templateId, templateVersion, bindings = sortedBindings });
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
    }

    private static bool IsTerminal(string status) => status is "SUCCEEDED" or "FAILED" or "CANCELLED";
}

public sealed class ProcessingStageViewModel(string stageId, string name) : ObservableObject
{
    private string _status = "PENDING";
    private string? _message;
    private string? _errorCode;
    public string StageId { get; } = stageId;
    public string Name { get; private set; } = name;
    public string Status { get => _status; private set { if (SetProperty(ref _status, value)) { OnPropertyChanged(nameof(Glyph)); OnPropertyChanged(nameof(AccessibilityText)); } } }
    public string? Message { get => _message; private set => SetProperty(ref _message, value); }
    public string? ErrorCode { get => _errorCode; private set => SetProperty(ref _errorCode, value); }
    public string Glyph => Status switch { "COMPLETED" => "✓", "RUNNING" => "◌", "FAILED" => "!", "SKIPPED" => "–", _ => "○" };
    public string AccessibilityText => $"{Name}: {Status}";
    public void Apply(TemplateProcessingStageDto dto)
    {
        Name = dto.Name;
        OnPropertyChanged(nameof(Name));
        Status = dto.Status.ToUpperInvariant();
        Message = dto.Message;
        ErrorCode = dto.ErrorCode;
    }
    public void Reset() { Status = "PENDING"; Message = null; ErrorCode = null; }
}
