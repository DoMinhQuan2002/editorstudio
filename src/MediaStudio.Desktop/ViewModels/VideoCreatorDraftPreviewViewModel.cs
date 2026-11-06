using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text.Json;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public sealed class VideoCreatorDraftPreviewViewModel : ObservableObject
{
    private readonly IVideoCreatorDraftPreviewService _service;
    private readonly Action _back;
    private readonly Action<VideoCreatorDraftPreviewViewModel>? _replaceMedia;
    private readonly Action<Screen6DraftHandoff>? _openExport;
    private readonly string _draftProjectId;
    private readonly string? _expectedTemplateId;
    private readonly string? _expectedTemplateVersion;
    private readonly bool _templateDefinitionAvailable;
    private VideoProjectDto? _project;
    private CancellationTokenSource? _previewRequest;
    private long _previewRequestId;
    private string _status = "Đang tải bản nháp Project V2...";
    private string? _errorMessage;
    private BitmapImage? _previewFrame;
    private BitmapImage? _firstFramePoster;
    private string? _previewVideoPath;
    private Uri? _previewVideoUri;
    private double _currentSeconds;
    private double _durationSeconds;
    private int _pendingAudioVolume = 100;
    private bool _pendingAudioMuted;
    private bool _isBusy;
    private bool _isReady;
    private bool _isPlaybackVerified;
    private bool _isPlaying;
    private bool _isPreviewMuted;
    private bool _audioSettingsAvailable;
    private long _previewFrameTimestampTicks;
    private string _audioUnavailableReason = "Mẫu này không có track âm thanh có thể chỉnh.";
    private string _textUnavailableReason = "Template Definition không khai báo trường chữ editable.";
    private string _compositionReference = "";
    private VideoCreatorOverlayAdjustmentViewModel? _selectedOverlay;
    private BitmapImage? _adjustmentPreviewFrame;
    private CancellationTokenSource? _adjustmentPreviewDelay;
    private bool _isApplyingOverlaySelection;
    private bool _isOverlayEditing;
    private bool _isLoadingOverlayEdit;
    private OverlayEditLayer? _overlayEditLayer;
    private CancellationTokenSource? _overlayEditRequest;

    public VideoCreatorDraftPreviewViewModel(
        IVideoCreatorDraftPreviewService service,
        string draftProjectId,
        string? expectedTemplateId,
        string? expectedTemplateVersion,
        Action back,
        Action<VideoCreatorDraftPreviewViewModel>? replaceMedia = null,
        bool templateDefinitionAvailable = true,
        Action<Screen6DraftHandoff>? openExport = null)
    {
        _service = service;
        _draftProjectId = draftProjectId;
        _expectedTemplateId = expectedTemplateId;
        _expectedTemplateVersion = expectedTemplateVersion;
        _templateDefinitionAvailable = templateDefinitionAvailable;
        _back = back;
        _replaceMedia = replaceMedia;
        _openExport = openExport;
        BackCommand = new RelayCommand(_ => _back());
        ReplaceMediaCommand = new RelayCommand(_ => _replaceMedia?.Invoke(this), _ => CanReplaceMedia);
        SaveDraftCommand = new AsyncRelayCommand(SaveDraftAsync, _ => CanSaveDraft);
        SelectSceneCommand = new RelayCommand(value =>
        {
            if (value is VideoCreatorPreviewSceneViewModel scene) _ = SelectSceneAsync(scene);
        }, value => !IsBusy && value is VideoCreatorPreviewSceneViewModel);
        ResetOverlayCommand = new RelayCommand(_ => SelectedOverlay?.Reset(), _ => SelectedOverlay is not null && !IsBusy);
        StartOverlayEditCommand = new RelayCommand(_ => _ = StartOverlayEditAsync(),
            _ => SelectedOverlay is not null && IsReady && !IsBusy && !IsOverlayEditing);
        FinishOverlayEditCommand = new RelayCommand(_ => FinishOverlayEdit(), _ => IsOverlayEditing);
        DiscardOverlayChangesCommand = new RelayCommand(_ => DiscardOverlayChanges(), _ => HasPlacementChanges && !IsBusy);
        NextCommand = new RelayCommand(_ =>
        {
            if (CanGoNext && Handoff is { } handoff) _openExport?.Invoke(handoff);
        }, _ => CanGoNext);
    }

    public ObservableCollection<VideoCreatorPreviewSceneViewModel> Scenes { get; } = [];
    public RelayCommand BackCommand { get; }
    public RelayCommand ReplaceMediaCommand { get; }
    public AsyncRelayCommand SaveDraftCommand { get; }
    public RelayCommand SelectSceneCommand { get; }
    public RelayCommand NextCommand { get; }
    public RelayCommand ResetOverlayCommand { get; }
    public RelayCommand DiscardOverlayChangesCommand { get; }
    public RelayCommand StartOverlayEditCommand { get; }
    public RelayCommand FinishOverlayEditCommand { get; }
    /// <summary>True while the selected overlay is moved and resized directly on the preview.</summary>
    public bool IsOverlayEditing
    {
        get => _isOverlayEditing;
        private set
        {
            if (!SetProperty(ref _isOverlayEditing, value)) return;
            OnPropertyChanged(nameof(IsAdjustmentPreviewVisible));
            StartOverlayEditCommand.NotifyCanExecuteChanged();
            FinishOverlayEditCommand.NotifyCanExecuteChanged();
        }
    }
    public bool IsLoadingOverlayEdit { get => _isLoadingOverlayEdit; private set => SetProperty(ref _isLoadingOverlayEdit, value); }
    /// <summary>Background without the selected overlay, plus the overlay image and its template placement.</summary>
    public OverlayEditLayer? OverlayEditLayer { get => _overlayEditLayer; private set => SetProperty(ref _overlayEditLayer, value); }
    public ObservableCollection<VideoCreatorOverlayAdjustmentViewModel> Overlays { get; } = [];
    public bool HasOverlays => Overlays.Count > 0;
    public VideoCreatorOverlayAdjustmentViewModel? SelectedOverlay
    {
        get => _selectedOverlay;
        set
        {
            if (!SetProperty(ref _selectedOverlay, value)) return;
            OnPropertyChanged(nameof(HasSelectedOverlay));
            ResetOverlayCommand.NotifyCanExecuteChanged();
            if (value is not null && IsOverlayEditing) _ = LoadOverlayEditLayerAsync(value);
            else if (value is not null && !_isApplyingOverlaySelection) _ = JumpToOverlayAsync(value);
        }
    }
    public bool HasSelectedOverlay => SelectedOverlay is not null;
    /// <summary>Frame rendered from the unsaved placement edit; shown over the player.</summary>
    public BitmapImage? AdjustmentPreviewFrame
    {
        get => _adjustmentPreviewFrame;
        private set { if (SetProperty(ref _adjustmentPreviewFrame, value)) OnPropertyChanged(nameof(IsAdjustmentPreviewVisible)); }
    }
    public bool IsAdjustmentPreviewVisible => !IsOverlayEditing && HasPlacementChanges && AdjustmentPreviewFrame is not null;
    public bool HasPlacementChanges => Overlays.Any(item => item.IsModified);
    public bool HasUnsavedChanges => HasAudioChanges || HasPlacementChanges;
    public event Action<TimeSpan>? PlaybackSeekRequested;

    public string ProjectId => _project?.ProjectId ?? _draftProjectId;
    public string TemplateId => _project?.TemplateId ?? _expectedTemplateId ?? "";
    public string TemplateVersion => ReadMetadataString(_project, "templateDefinitionVersion") ?? _expectedTemplateVersion ?? "Không rõ";
    public string TemplateName => _project?.Title ?? "Bản nháp video";
    public int Revision => _project?.Revision ?? 0;
    public IReadOnlyDictionary<string, string> MediaBindings =>
        _project is null ? new Dictionary<string, string>() : ReadMetadataStringMap(_project, "templateBindings");
    public string RevisionLabel => Revision > 0 ? $"Revision {Revision}" : "";
    public string ResolutionLabel => _project is null ? "" : $"{_project.Width} × {_project.Height}";
    public string AspectRatioLabel => _project is null ? "" : FormatAspect(_project.Width, _project.Height);
    public string DurationLabel => TimeSpan.FromSeconds(DurationSeconds).ToString(@"mm\:ss", CultureInfo.InvariantCulture);
    public string SceneCountLabel => $"Các cảnh trong video ({Scenes.Count})";
    public string Status { get => _status; private set => SetProperty(ref _status, value); }
    public string? ErrorMessage { get => _errorMessage; private set => SetProperty(ref _errorMessage, value); }
    public BitmapImage? PreviewFrame { get => _previewFrame; private set => SetProperty(ref _previewFrame, value); }
    public long PreviewFrameTimestampTicks { get => _previewFrameTimestampTicks; private set => SetProperty(ref _previewFrameTimestampTicks, value); }
    public Uri? PreviewVideoUri { get => _previewVideoUri; private set => SetProperty(ref _previewVideoUri, value); }
    public string? PreviewVideoPath { get => _previewVideoPath; private set => SetProperty(ref _previewVideoPath, value); }
    public double CurrentSeconds
    {
        get => _currentSeconds;
        set
        {
            if (!SetProperty(ref _currentSeconds, Math.Clamp(value, 0, Math.Max(0, DurationSeconds)))) return;
            OnPropertyChanged(nameof(CurrentTimeLabel));
        }
    }
    public double DurationSeconds { get => _durationSeconds; private set { if (SetProperty(ref _durationSeconds, value)) { OnPropertyChanged(nameof(DurationLabel)); OnPropertyChanged(nameof(CurrentSeconds)); } } }
    public string CurrentTimeLabel => TimeSpan.FromSeconds(CurrentSeconds).ToString(@"mm\:ss", CultureInfo.InvariantCulture);
    public bool IsBusy { get => _isBusy; private set { if (SetProperty(ref _isBusy, value)) RefreshCommands(); } }
    public bool IsReady { get => _isReady; private set { if (SetProperty(ref _isReady, value)) { OnPropertyChanged(nameof(CanGoNext)); RefreshCommands(); } } }
    public bool IsPlaybackVerified { get => _isPlaybackVerified; private set { if (SetProperty(ref _isPlaybackVerified, value)) RefreshCommands(); } }
    public bool IsPlaying { get => _isPlaying; private set => SetProperty(ref _isPlaying, value); }
    public bool IsPreviewMuted { get => _isPreviewMuted; set => SetProperty(ref _isPreviewMuted, value); }
    public bool IsAudioSettingsAvailable { get => _audioSettingsAvailable; private set => SetProperty(ref _audioSettingsAvailable, value); }
    public string AudioUnavailableReason { get => _audioUnavailableReason; private set => SetProperty(ref _audioUnavailableReason, value); }
    public string TextUnavailableReason { get => _textUnavailableReason; private set => SetProperty(ref _textUnavailableReason, value); }
    public string NextDisabledReason => _openExport is null ? "Màn 6 chưa được triển khai."
        : HasUnsavedChanges ? "Hãy lưu thay đổi bản nháp trước khi xuất video."
        : !IsPlaybackVerified ? "Hãy chờ video preview mở và xác minh thời lượng."
        : !IsReady || IsBusy ? "Bản nháp đang được xác minh."
        : "Sẵn sàng xuất bản nháp hiện tại.";
    public bool CanGoNext => _openExport is not null && IsReady && IsPlaybackVerified && !IsBusy
        && !HasUnsavedChanges && !string.IsNullOrWhiteSpace(PreviewVideoPath) && File.Exists(PreviewVideoPath)
        && Scenes.Count > 0 && !string.IsNullOrWhiteSpace(Scenes[0].SourceFingerprint);
    public bool CanSaveDraft => IsReady && !IsBusy && HasUnsavedChanges;
    public bool CanReplaceMedia => IsReady && !IsBusy && _replaceMedia is not null && CanUseTemplateDefinition;
    public string ReplacementDisabledReason => CanUseTemplateDefinition
        ? "Thay media bằng thư viện; giữ nguyên Template ID, phiên bản và Project ID."
        : "Không có đúng phiên bản Template Definition để xác thực thay media; bản nháp vẫn được giữ nguyên.";
    public int PendingAudioVolume
    {
        get => _pendingAudioVolume;
        set { if (SetProperty(ref _pendingAudioVolume, Math.Clamp(value, 0, 100))) { OnPropertyChanged(nameof(AudioVolumeLabel)); RefreshCommands(); } }
    }
    public bool PendingAudioMuted
    {
        get => _pendingAudioMuted;
        set { if (SetProperty(ref _pendingAudioMuted, value)) RefreshCommands(); }
    }
    public string AudioVolumeLabel => $"{PendingAudioVolume}%";
    public string SaveStatusLabel => HasUnsavedChanges ? "Có thay đổi chưa lưu" : "Bản nháp đã lưu";
    public bool HasAudioChanges
    {
        get
        {
            var project = _project;
            if (project is null || project.AudioTracks.Count != 1) return false;
            var audio = project.AudioTracks[0];
            var track = project.Tracks.FirstOrDefault(item => item.TrackId == audio.LaneTrackId);
            return Math.Abs(audio.Volume - PendingAudioVolume / 100d) > 0.0001
                || (track?.State.Muted ?? false) != PendingAudioMuted;
        }
    }
    public bool CanUseTemplateDefinition => _project is not null
        && _templateDefinitionAvailable
        && !string.IsNullOrWhiteSpace(_expectedTemplateId)
        && _project.TemplateId == _expectedTemplateId
        && ReadMetadataString(_project, "templateDefinitionVersion") == _expectedTemplateVersion;
    public string CompositionReference => _compositionReference;
    public Screen6DraftHandoff? Handoff => IsReady ? new Screen6DraftHandoff(
        ProjectId, Revision, TemplateId, TemplateVersion, CompositionReference,
        Scenes.Count > 0 ? Scenes[0].SourceFingerprint : "", PreviewVideoPath ?? "", _firstFramePoster, 0) : null;

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        if (IsBusy) return;
        IsBusy = true;
        IsReady = false;
        ErrorMessage = null;
        Status = "Đang xác minh Project V2, media và template...";
        try
        {
            var project = await _service.GetProjectAsync(_draftProjectId, cancellationToken);
            ValidateProjectIdentity(project);
            _project = project;
            _compositionReference = $"/api/v1/video/projects/{project.ProjectId}";
            DurationSeconds = ProjectDurationTicks(project) / (double)Math.Max(1, project.Timebase);
            ConfigureAudioSettings(project);
            BuildSceneList(project);
            BuildOverlayList(project);
            NotifyProjectProperties();
            await RefreshPreviewAsync(cancellationToken);
            IsReady = true;
            Status = $"Đã dựng preview composition revision {project.Revision}; đang mở video trong trình phát.";
            ErrorMessage = null;
        }
        catch (Exception error)
        {
            ErrorMessage = $"Không thể mở bản nháp: {error.Message}";
            Status = "Bản nháp chưa sẵn sàng để xem.";
        }
        finally { IsBusy = false; RefreshCommands(); }
    }

    public async Task SeekToAsync(double seconds, CancellationToken cancellationToken = default)
    {
        if (_project is null || !IsReady) return;
        CurrentSeconds = seconds;
        PlaybackSeekRequested?.Invoke(TimeSpan.FromSeconds(CurrentSeconds));
        await RenderStillFrameAsync(TimeSpan.FromSeconds(CurrentSeconds), cancellationToken);
    }

    public Task RefreshStillFrameAsync(double seconds, CancellationToken cancellationToken = default)
    {
        if (_project is null || !IsReady) return Task.CompletedTask;
        var boundedSeconds = Math.Clamp(seconds, 0, DurationSeconds);
        return RenderStillFrameAsync(TimeSpan.FromSeconds(boundedSeconds), cancellationToken);
    }

    public void SetPlaybackPosition(TimeSpan position) => CurrentSeconds = position.TotalSeconds;

    public void MarkPlaybackOpened(TimeSpan duration)
    {
        IsPlaybackVerified = duration > TimeSpan.Zero
            && Math.Abs(duration.TotalSeconds - DurationSeconds) <= 1.0;
        if (!IsPlaybackVerified)
        {
            ErrorMessage = $"Video preview đã mở nhưng thời lượng ({duration.TotalSeconds:0.0}s) không khớp Composition Graph ({DurationSeconds:0.0}s).";
            Status = "Preview playback không khớp thời lượng bản nháp.";
            return;
        }
        ErrorMessage = null;
        Status = $"Video preview revision {Revision} đã được mở và kiểm tra thời lượng.";
    }

    public void MarkPlaybackFailed(string message)
    {
        IsPlaybackVerified = false;
        IsPlaying = false;
        ErrorMessage = $"Không phát được video preview: {message}";
        Status = "Video preview chưa phát được từ bản nháp hiện tại.";
    }

    public void SetIsPlaying(bool isPlaying) => IsPlaying = isPlaying;

    public async Task ReplaceMediaAsync(IReadOnlyDictionary<string, string> bindings)
    {
        if (_project is null || !CanUseTemplateDefinition)
            throw new InvalidOperationException("Không có đúng Template Definition để xác thực thay media.");
        var oldBindings = ReadMetadataStringMap(_project, "templateBindings");
        if (oldBindings.Count == 0 || oldBindings.Count != bindings.Count
            || oldBindings.Keys.Except(bindings.Keys, StringComparer.Ordinal).Any()
            || bindings.Keys.Except(oldBindings.Keys, StringComparer.Ordinal).Any())
            throw new InvalidDataException("Danh sách slot thay đổi khác với template; giữ nguyên bindings hiện tại.");

        var edit = CloneProject(_project);
        var updatedClipIds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var track in edit.Tracks)
        {
            foreach (var clip in track.Clips)
            {
                var slotId = ReadMetadataString(clip.TemplateMetadata, "slotId");
                if (string.IsNullOrWhiteSpace(slotId) || !bindings.TryGetValue(slotId, out var newMediaId)) continue;
                if (oldBindings.TryGetValue(slotId, out var currentMediaId) && currentMediaId == newMediaId) continue;
                if (track.Kind != "visual" || clip.ClipKind is not ("visual" or "image" or "video"))
                    throw new InvalidDataException($"Slot {slotId} không thuộc clip hình ảnh/video.");
                clip.MediaId = newMediaId;
                clip.SourceStartTicks = 0;
                updatedClipIds.Add(clip.ClipId);
            }
        }
        foreach (var clip in edit.Clips.Where(clip => updatedClipIds.Contains(clip.ClipId)))
        {
            var canonical = edit.Tracks.SelectMany(track => track.Clips).First(item => item.ClipId == clip.ClipId);
            clip.MediaId = canonical.MediaId;
            clip.SourceStartTicks = 0;
            clip.SourceStartMs = 0;
        }
        if (updatedClipIds.Count == 0)
            throw new InvalidDataException("Template Definition không có slot binding được biên dịch; bản nháp chưa bị thay đổi.");
        edit.TemplateMetadata["templateBindings"] = bindings.ToDictionary(
            item => item.Key, item => item.Value, StringComparer.Ordinal);

        IsBusy = true;
        IsReady = false;
        ErrorMessage = null;
        Status = "Đang lưu thay đổi media vào cùng Project V2...";
        try
        {
            var saved = await _service.SaveProjectAsync(edit);
            ValidateProjectIdentity(saved);
            if (saved.ProjectId != _draftProjectId || saved.Revision != edit.Revision + 1)
                throw new InvalidDataException("Backend trả về Project ID hoặc revision không mong đợi.");
            _project = saved;
            _compositionReference = $"/api/v1/video/projects/{saved.ProjectId}";
            DurationSeconds = ProjectDurationTicks(saved) / (double)Math.Max(1, saved.Timebase);
            ConfigureAudioSettings(saved);
            BuildSceneList(saved);
            BuildOverlayList(saved);
            AdjustmentPreviewFrame = null;
            NotifyProjectProperties();
            Status = $"Media đã lưu ở revision {saved.Revision}; đang render preview mới...";
            await RefreshPreviewAsync(CancellationToken.None);
            IsReady = true;
            Status = $"Media đã được lưu trong cùng bản nháp (revision {saved.Revision}); đang xác minh playback preview.";
            ErrorMessage = null;
        }
        catch (BackendApiException error) when (error.StatusCode == HttpStatusCode.Conflict)
        {
            ErrorMessage = "Bản nháp đã đổi ở nơi khác. Không ghi đè lên revision mới hơn; quay lại và mở lại bản nháp.";
            Status = "Thay media chưa được xác nhận. Bản nháp hiện tại trên máy chủ được giữ nguyên.";
            throw;
        }
        catch (Exception error)
        {
            ErrorMessage = $"Không thể cập nhật bản nháp: {error.Message}";
            Status = "Thay media chưa hoàn tất; các lựa chọn trong thư viện vẫn được giữ lại.";
            throw;
        }
        finally { IsBusy = false; RefreshCommands(); }
    }

    private async Task SaveDraftAsync()
    {
        if (_project is null || !CanSaveDraft) return;
        if (IsOverlayEditing) { _overlayEditRequest?.Cancel(); IsOverlayEditing = false; OverlayEditLayer = null; }
        IsBusy = true;
        IsReady = false;
        ErrorMessage = null;
        Status = "Đang lưu thay đổi vào Project V2...";
        try
        {
            var edit = CloneProject(_project);
            if (HasAudioChanges)
            {
                if (edit.AudioTracks.Count != 1)
                    throw new InvalidOperationException("Chỉnh âm lượng chỉ hỗ trợ đúng một track audio.");
                var audio = edit.AudioTracks[0];
                audio.Volume = PendingAudioVolume / 100d;
                var lane = edit.Tracks.FirstOrDefault(track => track.TrackId == audio.LaneTrackId)
                    ?? throw new InvalidDataException("Không tìm thấy track audio canonical trong Project V2.");
                lane.State.Muted = PendingAudioMuted;
            }
            ApplyOverlayAdjustments(edit);
            var saved = await _service.SaveProjectAsync(edit);
            ValidateProjectIdentity(saved);
            if (saved.ProjectId != _draftProjectId || saved.Revision != edit.Revision + 1)
                throw new InvalidDataException("Backend trả về Project ID hoặc revision không mong đợi.");
            _project = saved;
            ConfigureAudioSettings(saved);
            BuildSceneList(saved);
            BuildOverlayList(saved);
            AdjustmentPreviewFrame = null;
            NotifyProjectProperties();
            Status = "Thay đổi đã lưu; đang render lại preview theo revision mới...";
            await RefreshPreviewAsync(CancellationToken.None);
            IsReady = true;
            Status = $"Đã lưu bản nháp revision {saved.Revision}; đang xác minh playback preview.";
        }
        catch (Exception error)
        {
            ErrorMessage = error is BackendApiException { StatusCode: HttpStatusCode.Conflict }
                ? "Bản nháp đã được thay đổi ở nơi khác. Hãy quay lại tải phiên bản mới trước khi lưu."
                : $"Không lưu được thay đổi: {error.Message}";
            Status = "Thay đổi chưa được xác nhận là đã lưu.";
            if (_project is not null) ConfigureAudioSettings(_project, preservePending: true);
        }
        finally { IsBusy = false; IsReady = _project is not null && PreviewVideoPath is not null; RefreshCommands(); }
    }

    private void BuildOverlayList(VideoProjectDto project)
    {
        var previousClipId = SelectedOverlay?.ClipId;
        foreach (var item in Overlays) item.Changed -= OnOverlayAdjusted;
        Overlays.Clear();
        var clips = project.Tracks
            .Where(track => track.Kind == "visual")
            .SelectMany(track => track.Clips)
            .Where(clip => ReadBool(clip.Properties, "removeBackground"))
            .OrderBy(clip => clip.TimelineStartTicks)
            .ThenBy(clip => clip.ClipId, StringComparer.Ordinal)
            .ToArray();
        for (var index = 0; index < clips.Length; index++)
        {
            var clip = clips[index];
            var item = new VideoCreatorOverlayAdjustmentViewModel(
                clip.ClipId,
                ReadMetadataString(clip.TemplateMetadata, "eventId") ?? "",
                OverlayLabel(clip, index),
                clip.TimelineStartTicks,
                clip.DurationTicks,
                ReadDouble(clip.Properties, "userScale", 1.0),
                ReadDouble(clip.Properties, "userOffsetX", 0.0),
                ReadDouble(clip.Properties, "userOffsetY", 0.0));
            item.Changed += OnOverlayAdjusted;
            Overlays.Add(item);
        }
        _isApplyingOverlaySelection = true;
        try
        {
            SelectedOverlay = Overlays.FirstOrDefault(item => item.ClipId == previousClipId) ?? Overlays.FirstOrDefault();
        }
        finally { _isApplyingOverlaySelection = false; }
        OnPropertyChanged(nameof(HasOverlays));
        NotifyPlacementState();
    }

    private static string OverlayLabel(VideoTimelineClipDto clip, int index)
    {
        var slotId = ReadMetadataString(clip.TemplateMetadata, "slotId") ?? "";
        var match = System.Text.RegularExpressions.Regex.Match(slotId, @"group-(\d+)-overlay-(\d+)");
        return match.Success
            ? $"Nhóm {int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture)} · Ảnh {int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture)}"
            : $"Ảnh tách nền {index + 1}";
    }

    private void ApplyOverlayAdjustments(VideoProjectDto project)
    {
        var byClip = Overlays.ToDictionary(item => item.ClipId, StringComparer.Ordinal);
        foreach (var clip in project.Tracks.SelectMany(track => track.Clips))
        {
            if (!byClip.TryGetValue(clip.ClipId, out var item)) continue;
            SetOrRemove(clip.Properties, "userScale", Math.Round(item.Scale, 4), 1.0);
            SetOrRemove(clip.Properties, "userOffsetX", Math.Round(item.OffsetX, 4), 0.0);
            SetOrRemove(clip.Properties, "userOffsetY", Math.Round(item.OffsetY, 4), 0.0);
        }
    }

    private static void SetOrRemove(Dictionary<string, object?> properties, string key, double value, double neutral)
    {
        if (Math.Abs(value - neutral) < 0.0001) properties.Remove(key);
        else properties[key] = value;
    }

    private void DiscardOverlayChanges()
    {
        foreach (var item in Overlays) item.Revert();
        AdjustmentPreviewFrame = null;
        NotifyPlacementState();
    }

    private void OnOverlayAdjusted(VideoCreatorOverlayAdjustmentViewModel item)
    {
        NotifyPlacementState();
        // While editing on the preview the overlay is drawn locally; no render needed.
        if (IsOverlayEditing) return;
        if (!HasPlacementChanges) { AdjustmentPreviewFrame = null; return; }
        _adjustmentPreviewDelay?.Cancel();
        _adjustmentPreviewDelay?.Dispose();
        _adjustmentPreviewDelay = new CancellationTokenSource();
        _ = RenderAdjustmentPreviewAsync(item, _adjustmentPreviewDelay.Token);
    }

    private async Task RenderAdjustmentPreviewAsync(VideoCreatorOverlayAdjustmentViewModel item, CancellationToken token)
    {
        try
        {
            // Sliders fire continuously; render only once the value settles.
            await Task.Delay(250, token);
            if (_project is null) return;
            var snapshot = CloneProject(_project);
            ApplyOverlayAdjustments(snapshot);
            var ticks = PreviewTicksFor(item);
            var result = await _service.RenderFrameAsync(snapshot, ticks, token);
            if (token.IsCancellationRequested) return;
            AdjustmentPreviewFrame = DecodePng(result.PngBytes);
            Status = "Đang xem thử vị trí/kích thước mới. Bấm \"Lưu bản nháp\" để áp dụng vào video.";
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (!token.IsCancellationRequested) ErrorMessage = $"Không xem thử được thay đổi: {error.Message}";
        }
    }

    private async Task StartOverlayEditAsync()
    {
        if (SelectedOverlay is not { } item || _project is null) return;
        IsPlaying = false;
        IsOverlayEditing = true;
        await LoadOverlayEditLayerAsync(item);
    }

    /// <summary>
    /// Click on the preview: pick the top-most cut-out on screen at the current
    /// time (the latest one to appear) and start editing it, like CapCut.
    /// </summary>
    public async Task BeginOverlayEditAtCurrentTimeAsync()
    {
        if (_project is null || !IsReady || IsBusy || IsOverlayEditing || Overlays.Count == 0) return;
        var ticks = (long)(CurrentSeconds * Math.Max(1, _project.Timebase));
        var target = Overlays
            .Where(item => ticks >= item.StartTicks && ticks < item.StartTicks + item.DurationTicks)
            .OrderByDescending(item => item.StartTicks)
            .FirstOrDefault();
        if (target is null)
        {
            Status = "Không có ảnh tách nền nào ở thời điểm này. Tua tới đoạn có ảnh rồi bấm vào ảnh để chỉnh.";
            return;
        }
        _isApplyingOverlaySelection = true;
        try { SelectedOverlay = target; }
        finally { _isApplyingOverlaySelection = false; }
        await StartOverlayEditAsync();
    }

    private void FinishOverlayEdit()
    {
        _overlayEditRequest?.Cancel();
        IsOverlayEditing = false;
        OverlayEditLayer = null;
        // Show the real composition with the new placement until it is saved.
        if (SelectedOverlay is { } item && HasPlacementChanges) OnOverlayAdjusted(item);
        else AdjustmentPreviewFrame = null;
        RefreshCommands();
    }

    private async Task LoadOverlayEditLayerAsync(VideoCreatorOverlayAdjustmentViewModel item)
    {
        if (_project is null) return;
        _overlayEditRequest?.Cancel();
        _overlayEditRequest?.Dispose();
        _overlayEditRequest = new CancellationTokenSource();
        var token = _overlayEditRequest.Token;
        IsLoadingOverlayEdit = true;
        try
        {
            var ticks = PreviewTicksFor(item);
            CurrentSeconds = ticks / (double)Math.Max(1, _project.Timebase);
            PlaybackSeekRequested?.Invoke(TimeSpan.FromSeconds(CurrentSeconds));
            // The overlay's own manual values are drawn locally, so they do not
            // matter here; the other overlays' unsaved values do.
            var snapshot = CloneProject(_project);
            ApplyOverlayAdjustments(snapshot);
            var dto = await _service.GetOverlayEditLayerAsync(snapshot, item.ClipId, ticks, token);
            if (token.IsCancellationRequested || !ReferenceEquals(SelectedOverlay, item)) return;
            OverlayEditLayer = new OverlayEditLayer(
                item.ClipId,
                Math.Max(1, dto.CanvasWidth), Math.Max(1, dto.CanvasHeight),
                DecodePng(Convert.FromBase64String(dto.BackgroundPng)),
                DecodePng(Convert.FromBase64String(dto.LayerPng)),
                dto.BaseLeft, dto.BaseTop, dto.BaseWidth, dto.BaseHeight,
                dto.SubjectBox is { Length: 4 } box ? box : new[] { 0d, 0d, 1d, 1d });
            ErrorMessage = null;
            Status = "Kéo ảnh để di chuyển, kéo góc hoặc lăn chuột để đổi kích thước. Bấm Xong khi chỉnh xong.";
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (!token.IsCancellationRequested)
            {
                ErrorMessage = $"Không mở được chế độ chỉnh ảnh: {error.Message}";
                IsOverlayEditing = false;
                OverlayEditLayer = null;
            }
        }
        finally { if (!token.IsCancellationRequested) IsLoadingOverlayEdit = false; }
    }

    /// <summary>
    /// The moment at which this overlay is shown and is the top-most cut-out.
    /// Overlays accumulate, so an earlier overlay is still "active" while later
    /// ones cover it; using the current time then would show the wrong image.
    /// </summary>
    private long PreviewTicksFor(VideoCreatorOverlayAdjustmentViewModel item)
    {
        var timebase = Math.Max(1, _project?.Timebase ?? 90000);
        var end = item.StartTicks + item.DurationTicks;
        // The next overlay to appear on top of this one, if any, within its lifetime.
        var nextStart = Overlays
            .Where(other => !ReferenceEquals(other, item) && other.StartTicks > item.StartTicks && other.StartTicks < end)
            .Select(other => other.StartTicks)
            .DefaultIfEmpty(end)
            .Min();
        var current = (long)(CurrentSeconds * timebase);
        if (current >= item.StartTicks && current < nextStart) return current;
        return ShowcaseTicks(item.StartTicks, nextStart);
    }

    /// <summary>
    /// A frame a little after <paramref name="startTicks"/>, but before
    /// <paramref name="untilTicks"/>. Rendering exactly at an event's first tick
    /// can land on the previous frame, which then shows the overlay before it -
    /// the scene strip labelled the cup as the cat that way.
    /// </summary>
    private long ShowcaseTicks(long startTicks, long untilTicks)
    {
        var timebase = Math.Max(1, _project?.Timebase ?? 90000);
        var lead = Math.Min(timebase / 3, Math.Max(0, (untilTicks - startTicks) / 2));
        return startTicks + lead;
    }

    /// <summary>Where a scene card seeks to and samples its thumbnail.</summary>
    private long SceneSampleTicks(VideoCreatorPreviewSceneViewModel scene)
    {
        if (scene.StartTicks == 0) return 0;
        var overlay = Overlays.FirstOrDefault(item => item.EventId == scene.EventId);
        var end = scene.StartTicks + scene.DurationTicks;
        var nextStart = Overlays
            .Where(item => item.StartTicks > scene.StartTicks && item.StartTicks < end)
            .Select(item => item.StartTicks)
            .DefaultIfEmpty(end)
            .Min();
        return overlay is null ? ShowcaseTicks(scene.StartTicks, end) : ShowcaseTicks(scene.StartTicks, nextStart);
    }

    private async Task JumpToOverlayAsync(VideoCreatorOverlayAdjustmentViewModel item)
    {
        if (_project is null || !IsReady) return;
        CurrentSeconds = PreviewTicksFor(item) / (double)Math.Max(1, _project.Timebase);
        PlaybackSeekRequested?.Invoke(TimeSpan.FromSeconds(CurrentSeconds));
        if (HasPlacementChanges) OnOverlayAdjusted(item);
        else await RenderStillFrameAsync(TimeSpan.FromSeconds(CurrentSeconds));
    }

    private void NotifyPlacementState()
    {
        OnPropertyChanged(nameof(HasPlacementChanges));
        OnPropertyChanged(nameof(HasUnsavedChanges));
        OnPropertyChanged(nameof(IsAdjustmentPreviewVisible));
        RefreshCommands();
    }

    private static bool ReadBool(IDictionary<string, object?> values, string key) =>
        values.TryGetValue(key, out var raw) && raw switch
        {
            bool value => value,
            JsonElement { ValueKind: JsonValueKind.True } => true,
            _ => false,
        };

    private static double ReadDouble(IDictionary<string, object?> values, string key, double fallback)
    {
        if (!values.TryGetValue(key, out var raw)) return fallback;
        return raw switch
        {
            double value => value,
            float value => value,
            int value => value,
            long value => value,
            decimal value => (double)value,
            JsonElement { ValueKind: JsonValueKind.Number } element => element.GetDouble(),
            _ => fallback,
        };
    }

    private async Task SelectSceneAsync(VideoCreatorPreviewSceneViewModel scene)
    {
        if (_project is null) return;
        foreach (var item in Scenes) item.IsSelected = ReferenceEquals(item, scene);
        var overlay = Overlays.FirstOrDefault(item => item.EventId == scene.EventId);
        if (overlay is not null)
        {
            _isApplyingOverlaySelection = true;
            try { SelectedOverlay = overlay; }
            finally { _isApplyingOverlaySelection = false; }
        }
        CurrentSeconds = SceneSampleTicks(scene) / (double)Math.Max(1, _project.Timebase);
        PlaybackSeekRequested?.Invoke(TimeSpan.FromSeconds(CurrentSeconds));
        await RenderStillFrameAsync(TimeSpan.FromSeconds(CurrentSeconds));
    }

    private async Task RefreshPreviewAsync(CancellationToken cancellationToken)
    {
        if (_project is null) return;
        IsReady = false;
        Status = $"Đang dựng preview revision {_project.Revision} từ Composition Graph...";
        await RefreshStillAndThumbnailsAsync(cancellationToken);
        var videoPath = await _service.RenderPlaybackPreviewAsync(_project, cancellationToken);
        if (_project.Revision != Revision) return;
        SetPlaybackPreview(videoPath, _project.Revision);
        IsReady = true;
    }

    private async Task RefreshStillAndThumbnailsAsync(CancellationToken cancellationToken)
    {
        if (_project is null) return;
        await RenderStillFrameAsync(TimeSpan.FromSeconds(CurrentSeconds), cancellationToken);
        foreach (var scene in Scenes)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var result = await _service.RenderFrameAsync(_project, SceneSampleTicks(scene), cancellationToken);
            if (result.ProjectRevision != _project.Revision) continue;
            var frame = DecodePng(result.PngBytes);
            scene.Thumbnail = frame;
            if (scene.StartTicks == 0) _firstFramePoster = frame;
            scene.SourceFingerprint = result.SourceFingerprint;
        }
        OnPropertyChanged(nameof(Handoff));
        OnPropertyChanged(nameof(SceneCountLabel));
    }

    private async Task RenderStillFrameAsync(TimeSpan position, CancellationToken cancellationToken = default)
    {
        if (_project is null) return;
        var requestId = Interlocked.Increment(ref _previewRequestId);
        _previewRequest?.Cancel();
        _previewRequest?.Dispose();
        _previewRequest = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var token = _previewRequest.Token;
        try
        {
            var ticks = (long)Math.Clamp(position.TotalSeconds * _project.Timebase, 0, Math.Max(0, ProjectDurationTicks(_project) - 1));
            var result = await _service.RenderFrameAsync(_project, ticks, token);
            if (token.IsCancellationRequested || requestId != _previewRequestId || result.ProjectRevision != _project.Revision) return;
            PreviewFrame = DecodePng(result.PngBytes);
            PreviewFrameTimestampTicks = ticks;
            OnPropertyChanged(nameof(Handoff));
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (requestId == _previewRequestId) ErrorMessage = $"Không cập nhật được frame preview: {error.Message}";
        }
    }

    private void SetPlaybackPreview(string path, int revision)
    {
        if (_project is null || revision != _project.Revision)
            throw new InvalidDataException("Video playback preview thuộc revision khác với bản nháp.");
        if (!File.Exists(path)) throw new FileNotFoundException("Không tìm thấy tệp playback preview.", path);
        PreviewVideoPath = path;
        PreviewVideoUri = new Uri(path, UriKind.Absolute);
        IsPlaybackVerified = false;
        IsPlaying = false;
        OnPropertyChanged(nameof(PreviewVideoUri));
        OnPropertyChanged(nameof(PreviewVideoPath));
        OnPropertyChanged(nameof(Handoff));
    }

    private void ConfigureAudioSettings(VideoProjectDto project, bool preservePending = false)
    {
        IsAudioSettingsAvailable = project.AudioTracks.Count == 1
            && project.Tracks.Count(track => track.Kind == "audio" && track.Clips.Count > 0) == 1;
        if (IsAudioSettingsAvailable)
        {
            var audio = project.AudioTracks[0];
            var track = project.Tracks.First(item => item.TrackId == audio.LaneTrackId);
            if (!preservePending || !HasAudioChanges)
            {
                PendingAudioVolume = (int)Math.Round(Math.Clamp(audio.Volume, 0, 1) * 100);
                PendingAudioMuted = track.State.Muted;
            }
            AudioUnavailableReason = "";
        }
        else
        {
            AudioUnavailableReason = project.AudioTracks.Count == 0
                ? "Bản nháp này không có audio track; không tạo nhạc nền giả."
                : "Màn 5 hiện chỉ hỗ trợ chỉnh một audio track; các track được giữ nguyên.";
            PendingAudioVolume = 100;
            PendingAudioMuted = false;
        }
        OnPropertyChanged(nameof(AudioVolumeLabel));
        OnPropertyChanged(nameof(SaveStatusLabel));
    }

    private void BuildSceneList(VideoProjectDto project)
    {
        Scenes.Clear();
        var compiledClips = project.Tracks.SelectMany(track => track.Clips)
            .Where(clip => clip.ClipKind is "visual" or "image" or "video")
            .ToArray();
        var events = compiledClips
            .Select(clip => (Clip: clip, EventId: ReadMetadataString(clip.TemplateMetadata, "eventId")))
            .Where(item => !string.IsNullOrWhiteSpace(item.EventId))
            .GroupBy(item => item.EventId!, StringComparer.Ordinal)
            .Select(group => new
            {
                EventId = group.Key,
                StartTicks = group.Min(item => item.Clip.TimelineStartTicks),
                EndTicks = group.Max(item => item.Clip.TimelineStartTicks + item.Clip.DurationTicks),
            })
            .OrderBy(item => item.StartTicks)
            .ThenBy(item => item.EventId, StringComparer.Ordinal)
            .ToArray();

        if (events.Length == 0 && ProjectDurationTicks(project) > 0)
        {
            Scenes.Add(new VideoCreatorPreviewSceneViewModel(
                "Toàn bộ video", "Cảnh xem", 0, ProjectDurationTicks(project), ""));
        }
        else
        {
            foreach (var item in events)
            {
                var label = HumanizeEventId(item.EventId);
                Scenes.Add(new VideoCreatorPreviewSceneViewModel(
                    label, item.EventId, item.StartTicks, Math.Max(1, item.EndTicks - item.StartTicks), ""));
            }
        }
        OnPropertyChanged(nameof(SceneCountLabel));
        OnPropertyChanged(nameof(Handoff));
    }

    private void ValidateProjectIdentity(VideoProjectDto project)
    {
        if (project.SchemaVersion != 2 || project.ProjectId != _draftProjectId)
            throw new InvalidDataException("Project V2 không khớp draft ID được bàn giao.");
        if (!string.IsNullOrWhiteSpace(_expectedTemplateId) && project.TemplateId != _expectedTemplateId)
            throw new InvalidDataException("Project V2 không khớp Template ID của processing job.");
        if (!string.IsNullOrWhiteSpace(_expectedTemplateVersion)
            && ReadMetadataString(project, "templateDefinitionVersion") != _expectedTemplateVersion)
            throw new InvalidDataException("Project V2 không khớp phiên bản Template Definition.");
        if (project.Width <= 0 || project.Height <= 0 || project.Timebase <= 0 || ProjectDurationTicks(project) <= 0)
            throw new InvalidDataException("Project V2 thiếu khung hình, timebase hoặc thời lượng hợp lệ.");
    }

    private void NotifyProjectProperties()
    {
        OnPropertyChanged(nameof(ProjectId)); OnPropertyChanged(nameof(TemplateId));
        OnPropertyChanged(nameof(TemplateVersion)); OnPropertyChanged(nameof(TemplateName));
        OnPropertyChanged(nameof(Revision)); OnPropertyChanged(nameof(RevisionLabel));
        OnPropertyChanged(nameof(ResolutionLabel)); OnPropertyChanged(nameof(AspectRatioLabel));
        OnPropertyChanged(nameof(DurationLabel)); OnPropertyChanged(nameof(Handoff));
        OnPropertyChanged(nameof(HasAudioChanges)); OnPropertyChanged(nameof(CanSaveDraft));
        OnPropertyChanged(nameof(CanReplaceMedia)); OnPropertyChanged(nameof(ReplacementDisabledReason));
    }

    private void RefreshCommands()
    {
        ReplaceMediaCommand.NotifyCanExecuteChanged();
        SaveDraftCommand.NotifyCanExecuteChanged();
        SelectSceneCommand.NotifyCanExecuteChanged();
        NextCommand.NotifyCanExecuteChanged();
        ResetOverlayCommand.NotifyCanExecuteChanged();
        DiscardOverlayChangesCommand.NotifyCanExecuteChanged();
        StartOverlayEditCommand.NotifyCanExecuteChanged();
        FinishOverlayEditCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(CanSaveDraft)); OnPropertyChanged(nameof(SaveStatusLabel));
        OnPropertyChanged(nameof(AudioVolumeLabel)); OnPropertyChanged(nameof(CanGoNext));
        OnPropertyChanged(nameof(NextDisabledReason));
        OnPropertyChanged(nameof(CanReplaceMedia)); OnPropertyChanged(nameof(ReplacementDisabledReason));
    }

    private static long ProjectDurationTicks(VideoProjectDto project) => project.Tracks
        .SelectMany(track => track.Clips)
        .Select(clip => clip.TimelineStartTicks + clip.DurationTicks)
        .DefaultIfEmpty(0).Max();

    private static string FormatAspect(int width, int height)
    {
        if (width <= 0 || height <= 0) return "";
        var gcd = GreatestCommonDivisor(width, height);
        return $"{width / gcd}:{height / gcd}";
    }

    private static int GreatestCommonDivisor(int a, int b)
    {
        while (b != 0) (a, b) = (b, a % b);
        return Math.Max(1, a);
    }

    private static string HumanizeEventId(string value) => string.Join(" ",
        value.Replace('_', '-').Split('-', StringSplitOptions.RemoveEmptyEntries)
            .Select(piece => char.ToUpperInvariant(piece[0]) + piece[1..]));

    private static string? ReadMetadataString(VideoProjectDto? project, string key) =>
        project is null ? null : ReadMetadataString(project.TemplateMetadata, key);

    private static string? ReadMetadataString(IDictionary<string, object?> metadata, string key)
    {
        if (!metadata.TryGetValue(key, out var raw)) return null;
        return raw switch
        {
            string value => value,
            JsonElement { ValueKind: JsonValueKind.String } element => element.GetString(),
            _ => null,
        };
    }

    private static Dictionary<string, string> ReadMetadataStringMap(VideoProjectDto project, string key)
    {
        if (!project.TemplateMetadata.TryGetValue(key, out var raw)) return new(StringComparer.Ordinal);
        if (raw is JsonElement { ValueKind: JsonValueKind.Object } element)
        {
            var result = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var item in element.EnumerateObject())
            {
                if (item.Value.ValueKind != JsonValueKind.String) return new(StringComparer.Ordinal);
                result[item.Name] = item.Value.GetString() ?? "";
            }
            return result;
        }
        if (raw is IDictionary<string, string> map)
            return new Dictionary<string, string>(map, StringComparer.Ordinal);
        return new(StringComparer.Ordinal);
    }

    private static BitmapImage DecodePng(byte[] bytes)
    {
        using var stream = new MemoryStream(bytes);
        var bitmap = new BitmapImage();
        bitmap.BeginInit(); bitmap.CacheOption = BitmapCacheOption.OnLoad; bitmap.StreamSource = stream; bitmap.EndInit();
        bitmap.Freeze(); return bitmap;
    }

    private static VideoProjectDto CloneProject(VideoProjectDto project)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(project, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        return JsonSerializer.Deserialize<VideoProjectDto>(bytes, new JsonSerializerOptions(JsonSerializerDefaults.Web))
            ?? throw new InvalidDataException("Không thể tạo edit snapshot cho Project V2.");
    }
}

public sealed class VideoCreatorPreviewSceneViewModel(
    string label, string eventId, long startTicks, long durationTicks, string sourceFingerprint) : ObservableObject
{
    private BitmapImage? _thumbnail;
    private string _sourceFingerprint = sourceFingerprint;
    public string Label { get; } = label;
    public string EventId { get; } = eventId;
    public long StartTicks { get; } = startTicks;
    public long DurationTicks { get; } = durationTicks;
    public string DurationLabel { get; private set; } = $"{durationTicks / 90000d:0.0}s";
    public BitmapImage? Thumbnail { get => _thumbnail; set => SetProperty(ref _thumbnail, value); }
    public string SourceFingerprint { get => _sourceFingerprint; set => SetProperty(ref _sourceFingerprint, value); }

    private bool _isSelected;
    /// <summary>Highlighted in the scene strip after the user picks it.</summary>
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }

    /// <summary>Short badge for the scene strip: group number ("01") or a glyph for the title.</summary>
    public string Badge
    {
        get
        {
            var match = System.Text.RegularExpressions.Regex.Match(EventId, @"group-(\d+)");
            if (match.Success) return match.Groups[1].Value.PadLeft(2, '0');
            return EventId.Contains("title", StringComparison.OrdinalIgnoreCase) ? "T" : "";
        }
    }
    public bool HasBadge => Badge.Length > 0;
}

/// <summary>Manual size/position for one background-removed overlay.</summary>
public sealed class VideoCreatorOverlayAdjustmentViewModel : ObservableObject
{
    private readonly double _savedScale;
    private readonly double _savedOffsetX;
    private readonly double _savedOffsetY;
    private double _scale;
    private double _offsetX;
    private double _offsetY;

    public VideoCreatorOverlayAdjustmentViewModel(string clipId, string eventId, string label, long startTicks, long durationTicks,
        double scale, double offsetX, double offsetY)
    {
        ClipId = clipId;
        EventId = eventId;
        Label = label;
        StartTicks = startTicks;
        DurationTicks = durationTicks;
        _savedScale = _scale = Math.Clamp(scale, 0.2, 4.0);
        _savedOffsetX = _offsetX = Math.Clamp(offsetX, -1.0, 1.0);
        _savedOffsetY = _offsetY = Math.Clamp(offsetY, -1.0, 1.0);
    }

    public event Action<VideoCreatorOverlayAdjustmentViewModel>? Changed;
    public string ClipId { get; }
    public string Label { get; }
    public long StartTicks { get; }
    public long DurationTicks { get; }
    public string EventId { get; }
    public double Scale => _scale;
    public double OffsetX => _offsetX;
    public double OffsetY => _offsetY;

    /// <summary>Size as a percentage of the template's own placement (20–400).</summary>
    public double SizePercent
    {
        get => Math.Round(_scale * 100);
        set => Update(ref _scale, Math.Clamp(value, 20, 400) / 100d, nameof(SizePercent), nameof(SizeLabel));
    }
    /// <summary>Horizontal shift as a percentage of the frame width (−100 to 100).</summary>
    public double OffsetXPercent
    {
        get => Math.Round(_offsetX * 100);
        set => Update(ref _offsetX, Math.Clamp(value, -100, 100) / 100d, nameof(OffsetXPercent), nameof(OffsetXLabel));
    }
    /// <summary>Vertical shift as a percentage of the frame height (−100 to 100).</summary>
    public double OffsetYPercent
    {
        get => Math.Round(_offsetY * 100);
        set => Update(ref _offsetY, Math.Clamp(value, -100, 100) / 100d, nameof(OffsetYPercent), nameof(OffsetYLabel));
    }
    public string SizeLabel => $"{SizePercent:0}%";
    public string OffsetXLabel => $"{OffsetXPercent:+0;-0;0}%";
    public string OffsetYLabel => $"{OffsetYPercent:+0;-0;0}%";
    public bool IsModified => Math.Abs(_scale - _savedScale) > 0.0001
        || Math.Abs(_offsetX - _savedOffsetX) > 0.0001 || Math.Abs(_offsetY - _savedOffsetY) > 0.0001;

    /// <summary>Set all three values at once, as a mouse drag on the preview does.</summary>
    public void SetPlacement(double scale, double offsetX, double offsetY)
    {
        scale = Math.Round(Math.Clamp(scale, 0.2, 4.0), 4);
        offsetX = Math.Round(Math.Clamp(offsetX, -1.0, 1.0), 4);
        offsetY = Math.Round(Math.Clamp(offsetY, -1.0, 1.0), 4);
        if (Math.Abs(scale - _scale) < 0.00005 && Math.Abs(offsetX - _offsetX) < 0.00005
            && Math.Abs(offsetY - _offsetY) < 0.00005) return;
        _scale = scale; _offsetX = offsetX; _offsetY = offsetY;
        OnPropertyChanged(nameof(SizePercent)); OnPropertyChanged(nameof(SizeLabel));
        OnPropertyChanged(nameof(OffsetXPercent)); OnPropertyChanged(nameof(OffsetXLabel));
        OnPropertyChanged(nameof(OffsetYPercent)); OnPropertyChanged(nameof(OffsetYLabel));
        OnPropertyChanged(nameof(IsModified));
        Changed?.Invoke(this);
    }

    public void Reset()
    {
        SizePercent = 100;
        OffsetXPercent = 0;
        OffsetYPercent = 0;
    }

    public void Revert()
    {
        _scale = _savedScale; _offsetX = _savedOffsetX; _offsetY = _savedOffsetY;
        OnPropertyChanged(nameof(SizePercent)); OnPropertyChanged(nameof(SizeLabel));
        OnPropertyChanged(nameof(OffsetXPercent)); OnPropertyChanged(nameof(OffsetXLabel));
        OnPropertyChanged(nameof(OffsetYPercent)); OnPropertyChanged(nameof(OffsetYLabel));
        OnPropertyChanged(nameof(IsModified));
    }

    public override string ToString() => Label;

    private void Update(ref double field, double value, string property, string label)
    {
        value = Math.Round(value, 4);
        if (Math.Abs(field - value) < 0.00005) return;
        field = value;
        OnPropertyChanged(property);
        OnPropertyChanged(label);
        OnPropertyChanged(nameof(IsModified));
        Changed?.Invoke(this);
    }
}

/// <summary>
/// One overlay prepared for live editing. Base* is the template placement in
/// canvas fractions before manual adjustment; SubjectBox is the visible subject
/// inside the overlay image as [left, top, right, bottom] image fractions.
/// </summary>
public sealed record OverlayEditLayer(
    string ClipId,
    int CanvasWidth,
    int CanvasHeight,
    BitmapImage Background,
    BitmapImage Layer,
    double BaseLeft,
    double BaseTop,
    double BaseWidth,
    double BaseHeight,
    double[] SubjectBox);

public sealed record Screen6DraftHandoff(
    string DraftProjectId,
    int DraftRevision,
    string TemplateId,
    string TemplateVersion,
    string CompositionReference,
    string CompositionFingerprint,
    string PreviewVideoPath = "",
    BitmapImage? PreviewPoster = null,
    long PreviewPosterTimestampTicks = 0);
