using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public sealed class VideoCreatorExportViewModel : ObservableObject
{
    private static readonly Regex InvalidWindowsName = new("[<>:\"/\\\\|?*\\x00-\\x1f]", RegexOptions.Compiled);
    private static readonly Regex ReservedWindowsName = new("^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\\..*)?$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private readonly IVideoCreatorExportService _service;
    private readonly IVideoCreatorExportUi _ui;
    private readonly Screen6DraftHandoff _handoff;
    private readonly Action _back;
    private readonly string _defaultOutputDirectory;
    private VideoCreatorExportCapabilitiesDto? _capabilities;
    private string _status = "Đang xác minh bản nháp và khả năng xuất...";
    private string? _errorMessage;
    private string _fileName = "Video";
    private string _outputDirectory;
    private string _selectedQuality = "standard";
    private string _jobId = "";
    private string _requestId = "";
    private int? _progressPercent;
    private double _currentSeconds;
    private bool _isPreviewSourceVerified, _isPreviewLoading = true, _isPreviewMediaOpened, _isPreviewPlaying, _hasPreviewError;
    private string _previewStatus = "Đang xác minh video preview...";
    private TimeSpan? _previewNaturalDuration;
    private bool _isLoading, _isExporting, _isSucceeded, _isFailed, _isCancelled, _needsJobRecovery;
    private VideoExportResultDto? _result;

    public VideoCreatorExportViewModel(IVideoCreatorExportService service, IVideoCreatorExportUi ui,
        Screen6DraftHandoff handoff, Action back)
    {
        _service = service; _ui = ui; _handoff = handoff; _back = back;
        var videos = Environment.GetFolderPath(Environment.SpecialFolder.MyVideos);
        _outputDirectory = Directory.Exists(videos) ? videos : Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        _defaultOutputDirectory = _outputDirectory;
        BackCommand = new RelayCommand(_ => _back());
        ChooseFolderCommand = new RelayCommand(_ => ChooseFolder(), _ => !IsLoading && !IsExporting);
        ResetSettingsCommand = new RelayCommand(_ => ResetSettings(), _ => !IsLoading && !IsExporting);
        ExportCommand = new AsyncRelayCommand(StartExportAsync, _ => CanExport);
        CancelCommand = new AsyncRelayCommand(CancelAsync, _ => CanCancel);
        ReconnectCommand = new AsyncRelayCommand(ReconnectAsync, _ => NeedsJobRecovery && !IsLoading);
        RetryCommand = new AsyncRelayCommand(StartExportAsync, _ => CanRetry);
        OpenVideoCommand = new RelayCommand(_ => OpenVideo(), _ => IsSucceeded && Result is not null);
        OpenFolderCommand = new RelayCommand(_ => OpenOutputFolder(), _ => IsSucceeded && Result is not null);
    }

    public ObservableCollection<ExportQualityOption> QualityOptions { get; } = [];
    public RelayCommand BackCommand { get; }
    public RelayCommand ChooseFolderCommand { get; }
    public RelayCommand ResetSettingsCommand { get; }
    public AsyncRelayCommand ExportCommand { get; }
    public AsyncRelayCommand CancelCommand { get; }
    public AsyncRelayCommand ReconnectCommand { get; }
    public AsyncRelayCommand RetryCommand { get; }
    public RelayCommand OpenVideoCommand { get; }
    public RelayCommand OpenFolderCommand { get; }
    public string DraftProjectId => _handoff.DraftProjectId;
    public int DraftRevision => _handoff.DraftRevision;
    public string TemplateId => _handoff.TemplateId;
    public string TemplateVersion => _handoff.TemplateVersion;
    public string PreviewVideoPath => _handoff.PreviewVideoPath;
    public BitmapImage? PreviewPoster => _handoff.PreviewPoster;
    public bool IsPreviewSourceVerified { get => _isPreviewSourceVerified; private set => SetProperty(ref _isPreviewSourceVerified, value); }
    public bool IsPreviewLoading { get => _isPreviewLoading; private set => SetProperty(ref _isPreviewLoading, value); }
    public bool IsPreviewMediaOpened { get => _isPreviewMediaOpened; private set => SetProperty(ref _isPreviewMediaOpened, value); }
    public bool IsPreviewPlaying { get => _isPreviewPlaying; private set => SetProperty(ref _isPreviewPlaying, value); }
    public bool HasPreviewError { get => _hasPreviewError; private set => SetProperty(ref _hasPreviewError, value); }
    public string PreviewStatus { get => _previewStatus; private set => SetProperty(ref _previewStatus, value); }
    public string ProjectName { get; private set; } = "Bản nháp video";
    public string ResolutionLabel => _capabilities is null ? "Đang xác minh..." : $"{_capabilities.Width} × {_capabilities.Height}";
    public string FrameRateLabel => _capabilities is null ? "Đang xác minh..." : FormatFrameRate(_capabilities.FrameRateNumerator, _capabilities.FrameRateDenominator);
    public string DurationLabel => _capabilities is null ? "" : TimeSpan.FromSeconds(
        _capabilities.DurationTicks / (double)Math.Max(1, _capabilities.Timebase)).ToString(@"mm\:ss", CultureInfo.InvariantCulture);
    public double DurationSeconds => _capabilities is null ? 0 : _capabilities.DurationTicks / (double)Math.Max(1, _capabilities.Timebase);
    public double CurrentSeconds { get => _currentSeconds; set { if (SetProperty(ref _currentSeconds, Math.Clamp(value, 0, DurationSeconds))) OnPropertyChanged(nameof(CurrentTimeLabel)); } }
    public string CurrentTimeLabel => TimeSpan.FromSeconds(CurrentSeconds).ToString(@"mm\:ss", CultureInfo.InvariantCulture);
    public string FormatLabel => _capabilities is null ? "MP4 · H.264" : $"{_capabilities.Format.ToUpperInvariant()} · {(_capabilities.VideoCodec == "h264" ? "H.264" : _capabilities.VideoCodec)}";
    public string AudioCodecLabel => _capabilities?.HasAudio == true ? "AAC (có audio nguồn)" : "Không có audio nguồn";
    public bool HasAudio => _capabilities?.HasAudio == true;
    public bool SupportsCancel => _capabilities?.SupportsCancel == true;
    public string Status { get => _status; private set => SetProperty(ref _status, value); }
    public string? ErrorMessage { get => _errorMessage; private set { if (SetProperty(ref _errorMessage, value)) OnPropertyChanged(nameof(HasError)); } }
    public bool HasError => !string.IsNullOrWhiteSpace(ErrorMessage);
    public bool IsLoading { get => _isLoading; private set { if (SetProperty(ref _isLoading, value)) RefreshCommands(); } }
    public bool IsExporting { get => _isExporting; private set { if (SetProperty(ref _isExporting, value)) { OnPropertyChanged(nameof(IsProgressIndeterminate)); RefreshCommands(); } } }
    public bool IsProgressIndeterminate => IsExporting && ProgressPercent is null;
    public bool IsSucceeded { get => _isSucceeded; private set { if (SetProperty(ref _isSucceeded, value)) RefreshCommands(); } }
    public bool IsFailed { get => _isFailed; private set { if (SetProperty(ref _isFailed, value)) RefreshCommands(); } }
    public bool IsCancelled { get => _isCancelled; private set => SetProperty(ref _isCancelled, value); }
    public bool NeedsJobRecovery { get => _needsJobRecovery; private set { if (SetProperty(ref _needsJobRecovery, value)) RefreshCommands(); } }
    public int? ProgressPercent { get => _progressPercent; private set { if (SetProperty(ref _progressPercent, value)) OnPropertyChanged(nameof(IsProgressIndeterminate)); } }
    public string JobId { get => _jobId; private set => SetProperty(ref _jobId, value); }
    public VideoExportResultDto? Result { get => _result; private set { if (SetProperty(ref _result, value)) { OnPropertyChanged(nameof(ResultFileName)); OnPropertyChanged(nameof(ResultPath)); OnPropertyChanged(nameof(ResultResolution)); OnPropertyChanged(nameof(ResultDuration)); OnPropertyChanged(nameof(ResultSize)); RefreshCommands(); } } }
    public string ResultFileName => Result is null ? "" : Path.GetFileName(Result.OutputPath);
    public string ResultPath => Result?.OutputPath ?? "";
    public string ResultResolution => Result is null ? "" : $"{Result.Width} × {Result.Height}";
    public string ResultDuration => Result is null ? "" : TimeSpan.FromMilliseconds(Result.DurationMs).ToString(@"mm\:ss", CultureInfo.InvariantCulture);
    public string ResultSize => Result is null ? "" : FormatBytes(Result.SizeBytes);
    public string FileName { get => _fileName; set { if (SetProperty(ref _fileName, value)) { OnPropertyChanged(nameof(FileNameError)); RefreshCommands(); } } }
    public string OutputDirectory { get => _outputDirectory; set { if (SetProperty(ref _outputDirectory, value)) { OnPropertyChanged(nameof(OutputFilePath)); OnPropertyChanged(nameof(OutputAlreadyExists)); OnPropertyChanged(nameof(FreeSpaceLabel)); RefreshCommands(); } } }
    public string SelectedQuality { get => _selectedQuality; set { if (SetProperty(ref _selectedQuality, value)) RefreshCommands(); } }
    public string FileNameError => ValidateFileName(FileName) ?? "";
    public string OutputFilePath => string.IsNullOrWhiteSpace(OutputDirectory) || string.IsNullOrWhiteSpace(FileName)
        ? "" : Path.Combine(OutputDirectory, $"{GetFileStem(FileName)}.mp4");
    public bool OutputAlreadyExists => !string.IsNullOrWhiteSpace(OutputFilePath) && File.Exists(OutputFilePath);
    public string FreeSpaceLabel => GetFreeSpaceLabel(OutputDirectory);
    public bool CanExport => _capabilities?.CanExport == true && !IsLoading && !IsExporting && !NeedsJobRecovery && !IsSucceeded
        && ValidateFileName(FileName) is null && CanUseOutputDirectory(OutputDirectory)
        && QualityOptions.Any(x => x.Id == SelectedQuality);
    public bool CanCancel => IsExporting && SupportsCancel && !string.IsNullOrWhiteSpace(JobId);
    public bool CanRetry => IsFailed && CanExport;
    public string ExportButtonLabel => IsExporting ? "Đang xuất video..." : "Xuất video MP4  →";
    public string ProgressLabel => ProgressPercent is int p ? $"{p}%" : "Đang xử lý";

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        IsLoading = true; ErrorMessage = null;
        IsPreviewSourceVerified = false;
        IsPreviewLoading = true;
        IsPreviewMediaOpened = false;
        IsPreviewPlaying = false;
        _previewNaturalDuration = null;
        HasPreviewError = false;
        PreviewStatus = "Đang xác minh Project V2 và video preview...";
        Status = "Đang xác minh Project V2, revision, media bindings và renderer...";
        try
        {
            var project = await _service.GetProjectAsync(DraftProjectId, cancellationToken);
            if (project.ProjectId != _handoff.DraftProjectId || project.Revision != _handoff.DraftRevision || project.TemplateId != _handoff.TemplateId)
                throw new InvalidDataException("Bản nháp đã đổi ID, revision hoặc template sau khi duyệt. Hãy quay lại tải preview mới.");
            ProjectName = project.Title; OnPropertyChanged(nameof(ProjectName));
            FileName = MakeSafeDefaultFileName(project.Title);
            _capabilities = await _service.GetCapabilitiesAsync(DraftProjectId, cancellationToken);
            if (_capabilities.DraftRevision != _handoff.DraftRevision || _capabilities.TemplateId != _handoff.TemplateId
                || _capabilities.TemplateVersion != _handoff.TemplateVersion
                || !string.Equals(_capabilities.CompositionFingerprint, _handoff.CompositionFingerprint, StringComparison.Ordinal))
                throw new InvalidDataException("Composition Graph hoặc fingerprint không khớp video preview đã duyệt.");
            if (string.IsNullOrWhiteSpace(PreviewVideoPath) || !File.Exists(PreviewVideoPath))
                throw new FileNotFoundException("Không tìm thấy video preview của revision đã duyệt.", PreviewVideoPath);
            IsPreviewSourceVerified = true;
            IsPreviewLoading = true;
            PreviewStatus = "Đang mở video preview của revision đã duyệt...";
            VerifyPreviewDuration();
            QualityOptions.Clear();
            foreach (var quality in _capabilities.Qualities)
                QualityOptions.Add(new ExportQualityOption(quality, quality == "high" ? "Cao" : "Tiêu chuẩn"));
            if (_capabilities.ErrorMessage is not null) ErrorMessage = _capabilities.ErrorMessage;
            Status = _capabilities.CanExport
                ? "Bản nháp đã xác minh; MP4 sẽ giữ nguyên độ phân giải và frame rate của Project V2."
                : "Renderer hiện tại không hỗ trợ đầy đủ bản nháp này.";
            OnPropertyChanged(nameof(ResolutionLabel)); OnPropertyChanged(nameof(FrameRateLabel));
            OnPropertyChanged(nameof(DurationLabel)); OnPropertyChanged(nameof(FormatLabel));
            OnPropertyChanged(nameof(DurationSeconds));
            CurrentSeconds = Math.Clamp(
                _handoff.PreviewPosterTimestampTicks / (double)Math.Max(1, _capabilities.Timebase),
                0, DurationSeconds);
            OnPropertyChanged(nameof(AudioCodecLabel)); OnPropertyChanged(nameof(HasAudio));
            OnPropertyChanged(nameof(SupportsCancel));
        }
        catch (Exception error)
        {
            ErrorMessage = error.Message;
            Status = "Bản nháp chưa sẵn sàng để xuất.";
            SetPreviewError($"Không thể xác minh video preview: {error.Message}");
        }
        finally { IsLoading = false; RefreshCommands(); }
    }

    public void SetPlaybackPosition(TimeSpan position) => CurrentSeconds = position.TotalSeconds;
    public void SetIsPreviewPlaying(bool isPlaying) => IsPreviewPlaying = isPlaying;

    public void MarkPreviewMediaOpened(TimeSpan duration)
    {
        _previewNaturalDuration = duration;
        IsPreviewMediaOpened = duration > TimeSpan.Zero;
        IsPreviewLoading = false;
        VerifyPreviewDuration();
        if (!HasPreviewError && !IsPreviewLoading)
            PreviewStatus = PreviewPoster is null ? "Video đã sẵn sàng. Nhấn Phát để xem." : "";
    }

    public void SetPreviewPlaybackError(string message)
    {
        SetPreviewError($"Không phát được preview của bản nháp: {message}");
        Status = "Preview không khả dụng; hãy quay lại Screen 5 để tạo lại preview.";
    }

    private void VerifyPreviewDuration()
    {
        if (_previewNaturalDuration is not { } duration || DurationSeconds <= 0) return;
        if (duration <= TimeSpan.Zero || Math.Abs(duration.TotalSeconds - DurationSeconds) > 1.0)
        {
            SetPreviewError($"Thời lượng video preview ({duration.TotalSeconds:0.0}s) không khớp Project V2 ({DurationSeconds:0.0}s).");
            return;
        }
        IsPreviewSourceVerified = true;
        HasPreviewError = false;
        IsPreviewLoading = false;
        PreviewStatus = PreviewPoster is null ? "Video đã sẵn sàng. Nhấn Phát để xem." : "";
    }

    private void SetPreviewError(string message)
    {
        IsPreviewSourceVerified = false;
        IsPreviewLoading = false;
        IsPreviewMediaOpened = false;
        IsPreviewPlaying = false;
        HasPreviewError = true;
        PreviewStatus = message;
        ErrorMessage = message;
    }

    private void ChooseFolder()
    {
        var folder = _ui.PickOutputFolder(OutputDirectory);
        if (!string.IsNullOrWhiteSpace(folder)) OutputDirectory = folder;
    }

    private void ResetSettings()
    {
        SelectedQuality = "standard";
        FileName = MakeSafeDefaultFileName(ProjectName);
        OutputDirectory = _defaultOutputDirectory;
    }

    private async Task StartExportAsync()
    {
        if (!CanExport) return;
        // Premium templates need a plan to export; the gate shows the plan picker otherwise.
        if (!await ExportGate.AllowAsync(TemplateId)) return;
        var overwrite = OutputAlreadyExists;
        if (overwrite && !_ui.ConfirmOverwrite(OutputFilePath)) return;
        IsLoading = true; IsSucceeded = false; IsFailed = false; IsCancelled = false;
        NeedsJobRecovery = false; ProgressPercent = 0; ErrorMessage = null; Result = null;
        Status = "Đang tạo export job từ Project V2 đã xác minh...";
        try
        {
            var request = new VideoCreatorExportRequestDto
            {
                RequestId = string.IsNullOrWhiteSpace(_requestId) ? (_requestId = Guid.NewGuid().ToString("N")) : _requestId,
                DraftRevision = _handoff.DraftRevision, TemplateId = _handoff.TemplateId,
                TemplateVersion = _handoff.TemplateVersion, CompositionFingerprint = _handoff.CompositionFingerprint,
                MediaBindings = _capabilities!.MediaBindings, Quality = SelectedQuality,
                OutputDirectory = Path.GetFullPath(OutputDirectory), FileName = GetFileStem(FileName), Overwrite = overwrite,
            };
            var job = await _service.StartExportAsync(DraftProjectId, request);
            if (string.IsNullOrWhiteSpace(job.JobId)) throw new InvalidDataException("Backend không trả Export Job ID.");
            JobId = job.JobId; IsLoading = false; IsExporting = true; Status = job.Stage;
            await PollJobAsync();
        }
        catch (HttpRequestException error) { ErrorMessage = error.Message; Status = "Không xác nhận được phản hồi backend; không tạo job khác tự động."; IsFailed = true; }
        catch (Exception error) { ErrorMessage = error.Message; Status = "Không thể bắt đầu export."; IsFailed = true; }
        finally { IsLoading = false; RefreshCommands(); }
    }

    private async Task PollJobAsync()
    {
        while (!string.IsNullOrWhiteSpace(JobId))
        {
            VideoRenderJobDto job = null!;
            try { job = await _service.GetJobAsync(JobId); }
            catch (HttpRequestException error)
            {
                if (error.StatusCode is not null) { MarkJobRecovery(error.Message); return; }
                var recovered = false;
                for (var i = 0; i < 5; i++)
                {
                    await Task.Delay(800);
                    try { job = await _service.GetJobAsync(JobId); recovered = true; break; }
                    catch (HttpRequestException retryError)
                    {
                        if (retryError.StatusCode is not null) { MarkJobRecovery(retryError.Message); return; }
                    }
                }
                if (!recovered) { MarkJobRecovery(error.Message); return; }
            }
            ProgressPercent = job.Progress; Status = job.Stage;
            if (job.State.Equals("succeeded", StringComparison.OrdinalIgnoreCase))
            {
                var output = job.ExportResult;
                if (output is null || !output.FullDecodePassed || !File.Exists(output.OutputPath)
                    || new FileInfo(output.OutputPath).Length != output.SizeBytes)
                    throw new InvalidDataException("Backend báo hoàn tất nhưng file đã xác minh không còn hợp lệ trên đĩa.");
                Result = output; ProgressPercent = 100; IsExporting = false; IsSucceeded = true; IsFailed = false;
                Status = "Xuất video thành công!"; return;
            }
            if (job.State.Equals("failed", StringComparison.OrdinalIgnoreCase))
            {
                IsExporting = false; IsFailed = true; ErrorMessage = job.Error ?? "Backend không thể xuất video.";
                _requestId = Guid.NewGuid().ToString("N");
                Status = "Xuất video thất bại."; return;
            }
            if (job.State.Equals("cancelled", StringComparison.OrdinalIgnoreCase))
            {
                IsExporting = false; IsCancelled = true; _requestId = Guid.NewGuid().ToString("N");
                Status = "Đã hủy export. Project và media nguồn vẫn được giữ nguyên."; return;
            }
            await Task.Delay(450);
        }
    }

    private async Task CancelAsync()
    {
        if (!CanCancel) return;
        try { await _service.CancelJobAsync(JobId); Status = "Đang dừng renderer an toàn..."; }
        catch (Exception error) { ErrorMessage = $"Không thể gửi yêu cầu hủy: {error.Message}"; }
    }

    private async Task ReconnectAsync()
    {
        if (!NeedsJobRecovery || string.IsNullOrWhiteSpace(JobId)) return;
        IsLoading = true;
        try { NeedsJobRecovery = false; IsExporting = true; ErrorMessage = null; Status = $"Đang tìm lại export job {JobId}..."; await PollJobAsync(); }
        catch (Exception error) { MarkJobRecovery(error.Message); }
        finally { IsLoading = false; RefreshCommands(); }
    }

    private void MarkJobRecovery(string message)
    {
        IsExporting = false; NeedsJobRecovery = true;
        ErrorMessage = $"Kết nối backend bị gián đoạn. Export Job ID: {JobId}. Hãy truy vấn đúng job này trước khi tạo job mới. {message}";
        Status = "Trạng thái job đang chờ khôi phục.";
    }

    private void OpenVideo() { if (Result is not null && File.Exists(Result.OutputPath)) _ui.OpenFile(Result.OutputPath); }
    private void OpenOutputFolder()
    {
        var directory = Result is null ? null : Path.GetDirectoryName(Result.OutputPath);
        if (!string.IsNullOrWhiteSpace(directory) && Directory.Exists(directory)) _ui.OpenFolder(directory);
    }

    private void RefreshCommands()
    {
        ExportCommand?.NotifyCanExecuteChanged(); CancelCommand?.NotifyCanExecuteChanged();
        ReconnectCommand?.NotifyCanExecuteChanged(); RetryCommand?.NotifyCanExecuteChanged();
        ChooseFolderCommand?.NotifyCanExecuteChanged(); OpenVideoCommand?.NotifyCanExecuteChanged();
        ResetSettingsCommand?.NotifyCanExecuteChanged();
        OpenFolderCommand?.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(CanExport)); OnPropertyChanged(nameof(CanCancel)); OnPropertyChanged(nameof(CanRetry));
        OnPropertyChanged(nameof(ExportButtonLabel)); OnPropertyChanged(nameof(OutputAlreadyExists));
        OnPropertyChanged(nameof(OutputFilePath)); OnPropertyChanged(nameof(FreeSpaceLabel));
    }

    private static string? ValidateFileName(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || value != value.Trim()) return "Tên file không được để trống hoặc có khoảng trắng ở đầu/cuối.";
        var stem = GetFileStem(value);
        if (stem.Length == 0 || stem is "." or "..") return "Tên file không hợp lệ.";
        if (stem.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase)) return "Không nhập lặp đuôi .mp4.";
        if (InvalidWindowsName.IsMatch(stem) || stem.EndsWith('.') || stem.EndsWith(' ')) return "Tên file chứa ký tự không hợp lệ trên Windows.";
        if (ReservedWindowsName.IsMatch(stem)) return "Tên file trùng tên thiết bị dành riêng của Windows.";
        return stem.Length > 120 ? "Tên file vượt quá 120 ký tự." : null;
    }
    private static string GetFileStem(string value) => value.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase) ? value[..^4] : value;
    private static string MakeSafeDefaultFileName(string value)
    {
        var safe = InvalidWindowsName.Replace(value, " ").Trim().TrimEnd('.', ' ');
        if (safe.Length > 120) safe = safe[..120].TrimEnd('.', ' ');
        return string.IsNullOrWhiteSpace(safe) || ReservedWindowsName.IsMatch(safe) ? "Video" : safe;
    }
    private static string FormatFrameRate(int numerator, int denominator) =>
        denominator <= 0 ? "Không xác định" : denominator == 1 ? $"{numerator} fps" : $"{numerator}/{denominator} fps";
    private static string GetFreeSpaceLabel(string path)
    {
        try
        {
            var root = Path.GetPathRoot(path);
            var drive = DriveInfo.GetDrives().FirstOrDefault(item => string.Equals(item.Name, root, StringComparison.OrdinalIgnoreCase) && item.IsReady);
            return drive is null ? "Dung lượng trống chưa xác định" : $"Khoảng trống: {FormatBytes(drive.AvailableFreeSpace)}";
        }
        catch { return "Dung lượng trống chưa xác định"; }
    }
    private static bool CanUseOutputDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        try
        {
            var fullPath = Path.GetFullPath(path);
            if (Directory.Exists(fullPath)) return true;
            var parent = Directory.GetParent(fullPath);
            return parent is not null && Directory.Exists(parent.FullName);
        }
        catch { return false; }
    }
    private static string FormatBytes(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        var value = (double)Math.Max(0, bytes); var unit = 0;
        while (value >= 1024 && unit < units.Length - 1) { value /= 1024; unit++; }
        return $"{value:0.#} {units[unit]}";
    }
}

public sealed record ExportQualityOption(string Id, string Label);
