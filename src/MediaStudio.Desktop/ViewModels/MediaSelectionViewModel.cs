using System.Collections.ObjectModel;
using System.IO;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public sealed class MediaSelectionViewModel : ObservableObject
{
    private const int FallDiaryMaxMedia = 36;
    private const int FallDiaryFirstBackgroundDurationMs = 5_200;
    private const int FallDiarySubsequentBackgroundDurationMs = 4_000;
    private readonly IMediaSelectionService _service;
    private readonly IMediaFilePicker _picker;
    private readonly Func<MediaSelectionSessionRequest, string, Dictionary<string, string>, Task>? _continueToProcessing;
    private readonly Func<MediaSelectionSessionRequest, string, Dictionary<string, string>, Task>? _applyMediaReplacement;
    private readonly List<SelectionMediaItem> _library = [];
    private string _filter = "all";
    private bool _isBulkSelecting;
    private SelectionMediaItem? _markAnchor;
    public bool IsBulkSelecting
    {
        get => _isBulkSelecting;
        set { if (IsBusy || !SetProperty(ref _isBulkSelecting, value)) return; if (!value) SetLibraryMarks([]); }
    }
    public int MarkedMediaCount => _library.Count(item => item.IsLibraryMarked);
    public bool HasMarkedMedia => MarkedMediaCount > 0;
    public string DeleteLibraryLabel => $"Xóa ({MarkedMediaCount})";
    public AsyncRelayCommand DeleteLibraryCommand { get; }
    public RelayCommand MarkAllLibraryCommand { get; }
    public RelayCommand AddToSelectionCommand { get; }
    private string _status = "Thêm ảnh hoặc video để bắt đầu. Các vị trí bắt buộc cần được gán đầy đủ.";
    private bool _busy;
    private SelectionMediaItem? _activeMedia;
    private string? _preparedPayload;
    private readonly IStoryTemplateService? _storyService;
    private int _storyPage = 1;
    private BitmapImage? _storyPreviewImage;
    private CancellationTokenSource? _storyPreviewRequest;
    private bool _isStoryPreviewLoading;
    public VideoTemplateDto Template { get; }
    public MediaSelectionSessionRequest Request { get; }
    private bool IsDynamicFallDiary => Template.TemplateId == "fall-diary"
        && (Template.TemplateDefinitionVersion is "0.6.0-dynamic-batches" or "0.7.0-reference-timing" or "0.8.0-intro-title" or "0.9.0-reference-overlays");
    private bool IsReferenceTimingFallDiary => Template.TemplateId == "fall-diary"
        && (Template.TemplateDefinitionVersion is "0.7.0-reference-timing" or "0.8.0-intro-title" or "0.9.0-reference-overlays");
    private bool IsAutumnLove40 => Template.TemplateId == "autumn-love-40"
        && Template.TemplateDefinitionVersion == "1.0.0-reference-sequence";
    public ObservableCollection<SelectionMediaItem> Media { get; } = [];
    public ObservableCollection<SelectionMediaItem> Selected { get; } = [];
    public ObservableCollection<SelectionSlot> Slots { get; } = [];
    public string Heading => IsDynamicFallDiary
        ? $"{Template.Name} · tối đa {FallDiaryMaxMedia} media · {Template.AspectRatio}"
        : $"{Template.Name} · {Template.DurationMs / 1000.0:0.#} giây · {Slots.Count} vị trí · {Template.AspectRatio}";
    public string SelectionSummary => IsDynamicFallDiary
        ? $"Đã chọn {Selected.Count} / {FallDiaryMaxMedia} media · Đã gán {Slots.Count(s => s.Media is not null)} / {Selected.Count} media"
        : $"Đã chọn {Selected.Count} / {_library.Count} media · Đã gán {Slots.Count(s => s.Media is not null)} / {Slots.Count} vị trí";
    public string ContinueButtonLabel => _applyMediaReplacement is null ? "Tiếp theo: Xử lý" : "Cập nhật preview";
    public string PageHeading => _applyMediaReplacement is null ? "Chọn media cho mẫu" : "Thay media trong bản nháp";
    public string PageDescription => _applyMediaReplacement is null
        ? IsDynamicFallDiary
            ? "Chọn tối đa 36 media theo thứ tự. Media số 1, 10, 19, 28 làm nền (ảnh hoặc video); nền đầu dài 5,2 giây, mỗi nền sau 4 giây. Tối đa 8 ảnh tiếp theo mỗi nhóm sẽ tự tách nền và lần lượt phủ lên."
            : IsAutumnLove40
                ? "Chọn đúng 40 media theo thứ tự mẫu. Mỗi khung có thời lượng riêng; ảnh và video đều dùng được. Nếu media chưa hợp lệ, trạng thái bên dưới sẽ chỉ rõ media và vị trí cần sửa."
                : "Bấm ảnh/video theo thứ tự muốn dùng; app tự xếp vào mẫu theo đúng thứ tự đó. Muốn thay một media: kéo media từ thư viện thả lên media đó ở hàng \"Media đã chọn\" bên dưới. Kéo các media trong hàng để đổi thứ tự."
        : IsDynamicFallDiary
            ? "Giữ nguyên bản nháp; chọn tối đa 36 media theo thứ tự. Vị trí 1, 10, 19, 28 làm nền; nền đầu dài 5,2 giây, mỗi nền sau 4 giây. Các vị trí tiếp theo trong nhóm là ảnh phủ tự động tách nền."
            : IsAutumnLove40
                ? "Giữ nguyên bản nháp; chọn đúng 40 ảnh/video theo thứ tự mẫu. Ảnh chân dung tại các khung phủ sẽ được tách nền; video tại các khung đó hiển thị toàn khung."
                : "Giữ nguyên template và bản nháp; chọn media theo thứ tự để tự gán vào các vị trí tương thích, rồi có thể đổi từng vị trí thủ công.";
    public string Status { get => _status; private set => SetProperty(ref _status, value); }
    public string? PreparedPayload { get => _preparedPayload; private set => SetProperty(ref _preparedPayload, value); }
    public SelectionMediaItem? ActiveMedia
    {
        get => _activeMedia;
        private set { if (SetProperty(ref _activeMedia, value)) OnPropertyChanged(nameof(HasActiveMedia)); }
    }
    public bool IsBusy { get => _busy; private set { SetProperty(ref _busy, value); RefreshCommands(); } }
    public RelayCommand BackCommand { get; }
    public AsyncRelayCommand ImportCommand { get; }
    public AsyncRelayCommand ReloadCommand { get; }
    public AsyncRelayCommand PrepareCommand { get; }
    public AsyncRelayCommand ContinueCommand { get; }
    public RelayCommand ToggleCommand { get; }
    public RelayCommand LibraryToggleCommand { get; }
    public RelayCommand FocusCommand { get; }
    public RelayCommand AssignCommand { get; }
    public RelayCommand RemoveBindingCommand { get; }
    public RelayCommand ClearCommand { get; }
    public RelayCommand FilterCommand { get; }

    public static bool IsEligible(VideoTemplateDto? template) => template is not null
        && template.AvailabilityStatus is "PILOT_RENDERABLE" or "READY_FOR_USERS"
        && !string.IsNullOrWhiteSpace(template.TemplateDefinitionVersion)
        && template.MediaSlotRequirements.Count > 0
        && template.MediaSlotRequirements.Select(s => s.SlotId).Distinct().Count() == template.MediaSlotRequirements.Count
        && template.MediaSlotRequirements.All(s => !string.IsNullOrWhiteSpace(s.SlotId)
            && s.AllowedMediaKinds.Count > 0 && s.AllowedMediaKinds.All(k => k is "image" or "video")
            && s.ReusePolicy is "allow" or "unique_asset" && s.MissingSlotPolicy is "error" or "skip_event");

    public MediaSelectionViewModel(VideoTemplateDto template, MediaSelectionSessionRequest request,
        IMediaSelectionService service, IMediaFilePicker picker, Action back,
        Func<MediaSelectionSessionRequest, string, Dictionary<string, string>, Task>? continueToProcessing = null,
        Func<MediaSelectionSessionRequest, string, Dictionary<string, string>, Task>? applyMediaReplacement = null,
        IStoryTemplateService? storyService = null)
    {
        _storyService = storyService;
        if (!IsEligible(template) || request.TemplateId != template.TemplateId)
            throw new ArgumentException("Template chưa có definition hợp lệ.");
        Template = template; Request = request; _service = service; _picker = picker;
        _continueToProcessing = continueToProcessing;
        _applyMediaReplacement = applyMediaReplacement;
        if (IsDynamicFallDiary) ResizeFallDiarySlots(1);
        else foreach (var slot in template.MediaSlotRequirements) Slots.Add(new SelectionSlot(Slots.Count + 1, slot));
        BackCommand = new RelayCommand(_ => back());
        ImportCommand = new AsyncRelayCommand(ImportAsync, _ => !IsBusy);
        ReloadCommand = new AsyncRelayCommand(LoadAsync, _ => !IsBusy);
        DeleteLibraryCommand = new AsyncRelayCommand(DeleteLibraryAsync, _ => !IsBusy && MarkedMediaCount is > 0 and <= 500);
        MarkAllLibraryCommand = new RelayCommand(_ => { IsBulkSelecting = true; SetLibraryMarks(Media); }, _ => !IsBusy);
        AddToSelectionCommand = new RelayCommand(value =>
        {
            if (value is SelectionMediaItem item) AddToSelection(item);
        }, value => !IsBusy && value is SelectionMediaItem item && CanAddToSelection(item));
        PrepareCommand = new AsyncRelayCommand(PrepareAsync, _ => !IsBusy && ValidateBindings() is null);
        ContinueCommand = new AsyncRelayCommand(ContinueAsync,
            _ => !IsBusy && (_continueToProcessing is not null || _applyMediaReplacement is not null) && ValidateBindings() is null);
        ToggleCommand = new RelayCommand(value => { if (value is SelectionMediaItem item) Toggle(item); }, _ => !IsBusy);
        LibraryToggleCommand = new RelayCommand(value =>
        {
            if (value is not SelectionMediaItem item) return;
            MarkLibraryItem(item, extend: false, toggle: false);
        }, _ => !IsBusy);
        FocusCommand = new RelayCommand(value => { if (value is SelectionMediaItem item) ActiveMedia = item; });
        AssignCommand = new RelayCommand(value => { if (value is SelectionSlot slot && ActiveMedia is not null) Assign(slot, ActiveMedia); }, _ => !IsBusy);
        RemoveBindingCommand = new RelayCommand(value => { if (value is SelectionSlot slot) { slot.Media = null; Changed(); } }, _ => !IsBusy);
        ClearCommand = new RelayCommand(_ => { foreach (var item in Selected) item.Order = 0; Selected.Clear(); foreach (var slot in Slots) slot.Media = null; ActiveMedia = null; Changed(); }, _ => !IsBusy);
        FilterCommand = new RelayCommand(value =>
        {
            _filter = value as string ?? "all";
            ApplyFilter();
            OnPropertyChanged(nameof(IsFilterAll)); OnPropertyChanged(nameof(IsFilterImage)); OnPropertyChanged(nameof(IsFilterVideo));
        });
        PreviousStoryPageCommand = new RelayCommand(_ => StoryPage--, _ => IsStoryPreview && StoryPage > 1);
        NextStoryPageCommand = new RelayCommand(_ => StoryPage++, _ => IsStoryPreview && StoryPage < StoryPageCount);
        GoToStoryPageCommand = new RelayCommand(value => { if (value is StoryPageDot dot) StoryPage = dot.Page; });
        if (IsStoryPreview)
            for (var page = 1; page <= StoryPageCount; page++) StoryPageDots.Add(new StoryPageDot(page, page == 1));
    }

    // ---- Live page preview for photo story (image-set) templates ----
    public bool IsStoryPreview => Template.IsImageSet && _storyService is not null;
    public bool IsMediaPreview => !IsStoryPreview;
    public int StoryPageCount => Math.Max(1, Slots.Select(slot => StoryPageOf(slot.Rule.SlotId)).DefaultIfEmpty(1).Max());
    public ObservableCollection<StoryPageDot> StoryPageDots { get; } = [];
    public RelayCommand PreviousStoryPageCommand { get; }
    public RelayCommand NextStoryPageCommand { get; }
    public RelayCommand GoToStoryPageCommand { get; }
    public string StoryPageLabel => $"Trang {StoryPage} / {StoryPageCount}";
    public BitmapImage? StoryPreviewImage { get => _storyPreviewImage; private set => SetProperty(ref _storyPreviewImage, value); }
    public bool IsStoryPreviewLoading { get => _isStoryPreviewLoading; private set => SetProperty(ref _isStoryPreviewLoading, value); }
    public int StoryPage
    {
        get => _storyPage;
        set
        {
            value = Math.Clamp(value, 1, StoryPageCount);
            if (!SetProperty(ref _storyPage, value)) return;
            foreach (var dot in StoryPageDots) dot.IsCurrent = dot.Page == value;
            OnPropertyChanged(nameof(StoryPageLabel));
            PreviousStoryPageCommand?.NotifyCanExecuteChanged();
            NextStoryPageCommand?.NotifyCanExecuteChanged();
            ScheduleStoryPreview(immediate: true);
        }
    }

    private static int StoryPageOf(string slotId)
    {
        var match = System.Text.RegularExpressions.Regex.Match(slotId, @"^page-(\d+)-photo-\d+$");
        return match.Success ? int.Parse(match.Groups[1].Value) : 1;
    }

    private void ScheduleStoryPreview(bool immediate = false)
    {
        if (!IsStoryPreview) return;
        _storyPreviewRequest?.Cancel();
        _storyPreviewRequest?.Dispose();
        _storyPreviewRequest = new CancellationTokenSource();
        _ = RefreshStoryPreviewAsync(immediate ? 0 : 150, _storyPreviewRequest.Token);
    }

    private async Task RefreshStoryPreviewAsync(int delayMs, CancellationToken token)
    {
        try
        {
            if (delayMs > 0) await Task.Delay(delayMs, token);
            IsStoryPreviewLoading = true;
            var bytes = await _storyService!.RenderPagePreviewAsync(Template.TemplateId, StoryPage, BuildBindings(), 540, token);
            if (token.IsCancellationRequested) return;
            StoryPreviewImage = DecodePng(bytes);
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (!token.IsCancellationRequested) Status = $"Không dựng được xem trước trang {StoryPage}: {error.Message}";
        }
        finally { if (!token.IsCancellationRequested) IsStoryPreviewLoading = false; }
    }

    private static BitmapImage DecodePng(byte[] bytes)
    {
        using var stream = new MemoryStream(bytes);
        var image = new BitmapImage();
        image.BeginInit();
        image.CacheOption = BitmapCacheOption.OnLoad;
        image.StreamSource = stream;
        image.EndInit();
        image.Freeze();
        return image;
    }

    /// <summary>Show the page where <paramref name="item"/> lands, e.g. right after it is picked.</summary>
    private void ShowStoryPageOf(SelectionMediaItem item)
    {
        if (!IsStoryPreview) return;
        var slot = Slots.FirstOrDefault(candidate => ReferenceEquals(candidate.Media, item));
        if (slot is not null) StoryPage = StoryPageOf(slot.Rule.SlotId);
    }

    public async Task LoadAsync()
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var incoming = await _service.ListAsync();
            var ids = incoming.Select(dto => dto.AssetId).ToHashSet();
            var removed = _library.Where(item => !ids.Contains(item.Media.AssetId)).ToArray();
            foreach (var item in removed)
            {
                _library.Remove(item); Selected.Remove(item); item.Order = 0;
                foreach (var slot in Slots.Where(slot => slot.Media == item)) slot.Media = null;
                if (ActiveMedia == item) ActiveMedia = null;
            }
            foreach (var dto in incoming) await AddAsync(dto);
            if (removed.Length > 0) Changed();
            ApplyFilter();
            Status = IsDynamicFallDiary
                ? "Thư viện đã tải. Chọn media theo thứ tự; vị trí nền và ảnh phủ sẽ được gán tự động theo từng nhóm 9."
                : "Thư viện đã tải. Chọn media theo thứ tự muốn dùng; app sẽ tự gán vào các vị trí tương thích.";
            ScheduleStoryPreview(immediate: true);
        }
        catch (Exception error) { Status = $"Không tải được thư viện: {error.Message}"; }
        finally { IsBusy = false; OnPropertyChanged(nameof(SelectionSummary)); }
    }

    public async Task ApplyBindingsAsync(IReadOnlyDictionary<string, string> bindings)
    {
        if (_library.Count == 0) await LoadAsync();
        if (IsDynamicFallDiary)
        {
            if (bindings.Count is < 1 or > FallDiaryMaxMedia)
                throw new InvalidDataException($"Fall Diary cần từ 1 đến {FallDiaryMaxMedia} media đã lưu.");
            var expected = Template.MediaSlotRequirements.Take(bindings.Count).Select(slot => slot.SlotId).ToHashSet();
            if (bindings.Keys.Any(key => !expected.Contains(key)))
                throw new InvalidDataException("Media Fall Diary đã lưu không liền thứ tự theo từng nhóm 9.");
        }
        foreach (var item in Selected) item.Order = 0;
        Selected.Clear();
        if (IsDynamicFallDiary) ResizeFallDiarySlots(Math.Max(1, bindings.Count));
        foreach (var slot in Slots) slot.Media = null;
        foreach (var slot in Slots)
        {
            if (!bindings.TryGetValue(slot.Rule.SlotId, out var mediaId)) continue;
            var item = _library.FirstOrDefault(candidate => candidate.Media.AssetId == mediaId)
                ?? throw new InvalidDataException($"Media {mediaId} của vị trí {slot.Rule.SlotId} không còn trong thư viện.");
            if (!Selected.Contains(item)) Selected.Add(item);
            if (!Assign(slot, item)) throw new InvalidDataException(Status);
        }
        Changed();
        Status = "Đã khôi phục các binding hiện được lưu trong Project V2.";
    }

    public void SetStatus(string message) => Status = message;

    public void SetLibraryMarks(IEnumerable<SelectionMediaItem> items)
    {
        if (IsBusy) return;
        var marked = items.ToHashSet();
        foreach (var item in _library) item.IsLibraryMarked = Media.Contains(item) && marked.Contains(item);
        NotifyLibraryMarks();
    }

    public void MarkLibraryItem(SelectionMediaItem item, bool extend, bool toggle)
    {
        if (IsBusy || !Media.Contains(item)) return;
        IsBulkSelecting = true;
        var marked = toggle ? Media.Where(candidate => candidate.IsLibraryMarked).ToHashSet() : [];
        if (extend && _markAnchor is not null && Media.Contains(_markAnchor))
        {
            var start = Media.IndexOf(_markAnchor); var end = Media.IndexOf(item);
            foreach (var candidate in Media.Skip(Math.Min(start, end)).Take(Math.Abs(end - start) + 1)) marked.Add(candidate);
        }
        else
        {
            if (!toggle || !marked.Remove(item)) marked.Add(item);
            _markAnchor = item;
        }
        SetLibraryMarks(marked);
    }

    private bool CanAddToSelection(SelectionMediaItem item) => Media.Contains(item)
        && !Selected.Contains(item) && NextMediaRule is not null
        && GetAssignmentError(Slots.FirstOrDefault(slot => slot.Media is null)
            ?? new SelectionSlot(Selected.Count + 1, NextMediaRule), item) is null;

    private void AddToSelection(SelectionMediaItem item)
    {
        if (Selected.Contains(item)) { Status = $"{item.Media.FileName} đã được thêm vào mẫu."; return; }
        var rule = NextMediaRule;
        if (rule is null) { Status = "Không còn vị trí trống trong mẫu."; return; }
        var slot = Slots.FirstOrDefault(candidate => candidate.Media is null)
            ?? new SelectionSlot(Selected.Count + 1, rule);
        if (GetAssignmentError(slot, item) is { } error) { Status = error; return; }
        Selected.Add(item); ActiveMedia = item;
        AssignSelectionInOrder();
        ShowStoryPageOf(item);
    }

    private void NotifyLibraryMarks()
    {
        OnPropertyChanged(nameof(MarkedMediaCount)); OnPropertyChanged(nameof(HasMarkedMedia)); OnPropertyChanged(nameof(DeleteLibraryLabel));
        DeleteLibraryCommand?.NotifyCanExecuteChanged();
        AddToSelectionCommand?.NotifyCanExecuteChanged();
    }

    private async Task DeleteLibraryAsync()
    {
        var items = _library.Where(item => item.IsLibraryMarked).ToArray();
        if (IsBusy || items.Length is < 1 or > 500) return;
        IsBusy = true;
        try
        {
            await _service.DeleteFromLibraryAsync(items.Select(item => item.Media.AssetId).ToArray());
            foreach (var item in items)
            {
                _library.Remove(item); Selected.Remove(item); item.Order = 0; item.IsLibraryMarked = false;
                foreach (var slot in Slots.Where(slot => slot.Media == item)) slot.Media = null;
                if (ActiveMedia == item) ActiveMedia = null;
            }
            _markAnchor = null;
            AssignSelectionInOrder();
            Status = $"Đã xóa {items.Length} media khỏi thư viện. Các dự án đã lưu vẫn giữ media đang dùng.";
        }
        catch (Exception error) { Status = $"Không xóa được media: {error.Message}. Lựa chọn vẫn được giữ lại."; }
        finally { IsBusy = false; NotifyLibraryMarks(); }
    }

    private async Task AddAsync(VideoMediaDto dto)
    {
        if (MediaTypeResolver.Resolve(dto) is not (MediaAssetType.Image or MediaAssetType.Video)
            || _library.Any(i => i.Media.AssetId == dto.AssetId)) return;
        var item = new SelectionMediaItem(dto);
        _library.Add(item);
        if (dto.ThumbnailAvailable)
            try { item.Thumbnail = MediaSelectionService.DecodeThumbnail(await _service.ThumbnailAsync(dto.AssetId)); }
            catch { item.ThumbnailProblem = "Không tải được thumbnail"; }
    }

    private async Task ImportAsync()
    {
        var paths = _picker.PickMediaFiles();
        if (paths.Count == 0) return;
        IsBusy = true;
        var errors = new List<string>();
        foreach (var path in paths)
        {
            try
            {
                if (!new[] { ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v" }.Contains(Path.GetExtension(path).ToLowerInvariant()))
                    throw new InvalidOperationException("Chỉ hỗ trợ ảnh và video.");
                var dto = await _service.ImportAsync(path);
                if (MediaTypeResolver.Resolve(dto) is not (MediaAssetType.Image or MediaAssetType.Video)) throw new InvalidOperationException("Nội dung không phải ảnh/video hợp lệ.");
                await AddAsync(dto);
            }
            catch (Exception error) { errors.Add($"{Path.GetFileName(path)}: {error.Message}"); }
        }
        ApplyFilter(); IsBusy = false; OnPropertyChanged(nameof(SelectionSummary));
        Status = errors.Count == 0 ? $"Đã nhập {paths.Count} tệp. Chọn media trong thư viện để sử dụng." : string.Join("\n", errors);
    }

    public void Toggle(SelectionMediaItem item)
    {
        if (!_library.Contains(item)) return;
        if (Selected.Remove(item))
        {
            item.Order = 0;
            foreach (var slot in Slots.Where(s => s.Media == item)) slot.Media = null;
            if (ActiveMedia == item) ActiveMedia = Selected.LastOrDefault();
        }
        else
        {
            if (IsDynamicFallDiary && Selected.Count >= FallDiaryMaxMedia)
            {
                Status = $"Fall Diary chỉ nhận tối đa {FallDiaryMaxMedia} media cho mỗi video.";
                return;
            }
            Selected.Add(item); ActiveMedia = item;
            AssignSelectionInOrder();
            ShowStoryPageOf(item);
            return;
        }
        AssignSelectionInOrder();
    }

    public bool Assign(SelectionSlot slot, SelectionMediaItem item)
    {
        if (!Slots.Contains(slot) || !Selected.Contains(item)) { Status = "Hãy chọn media trước khi gán."; return false; }
        if (GetAssignmentError(slot, item) is { } assignmentError) { Status = assignmentError; return false; }
        var rule = slot.Rule;
        if (Slots.Any(s => s != slot && s.Media == item && (rule.ReusePolicy == "unique_asset" || s.Rule.ReusePolicy == "unique_asset")))
        { Status = "Vị trí này không cho phép dùng lại cùng media."; return false; }
        slot.Media = item; Changed(); Status = $"Đã gán {item.Media.FileName} vào vị trí {slot.Index}."; return true;
    }

    private void AssignSelectionInOrder()
    {
        var selected = Selected.ToArray();
        if (IsDynamicFallDiary)
        {
            ResizeFallDiarySlots(Math.Max(1, selected.Length));
            foreach (var slot in Slots) slot.Media = null;
            var invalid = new List<string>();
            for (var i = 0; i < selected.Length; i++)
            {
                var slot = Slots[i];
                if (GetAssignmentError(slot, selected[i]) is { } error)
                {
                    invalid.Add(error);
                    continue;
                }
                slot.Media = selected[i];
            }
            Changed();
            if (selected.Length == 0)
                Status = "Đã bỏ chọn media; danh sách vị trí được đưa về nhóm đầu tiên.";
            else if (invalid.Count > 0)
                Status = $"Đã tự gán theo thứ tự. {string.Join(" ", invalid)} Hãy bỏ chọn media sai loại để các vị trí phía sau khớp đúng.";
            else
                Status = $"Đã tự gán {selected.Length} media theo thứ tự; mỗi nhóm dùng 1 nền và tối đa 8 ảnh phủ.";
            return;
        }

        foreach (var slot in Slots) slot.Media = null;

        // Match the ordered selection to ordered template slots, preserving both orders.
        // Required slots take priority so an optional slot cannot block the next required one.
        var requiredWeight = Slots.Count + 1;
        var best = new int[selected.Length + 1, Slots.Count + 1];
        for (var mediaIndex = 1; mediaIndex <= selected.Length; mediaIndex++)
        for (var slotIndex = 1; slotIndex <= Slots.Count; slotIndex++)
        {
            best[mediaIndex, slotIndex] = Math.Max(best[mediaIndex - 1, slotIndex], best[mediaIndex, slotIndex - 1]);
            var media = selected[mediaIndex - 1];
            var slot = Slots[slotIndex - 1];
            if (GetAssignmentError(slot, media) is null)
            {
                var required = slot.Rule.Required || slot.Rule.MissingSlotPolicy == "error";
                var score = best[mediaIndex - 1, slotIndex - 1] + (required ? requiredWeight : 1);
                best[mediaIndex, slotIndex] = Math.Max(best[mediaIndex, slotIndex], score);
            }
        }

        var assigned = 0;
        var mediaCursor = selected.Length;
        var slotCursor = Slots.Count;
        while (mediaCursor > 0 && slotCursor > 0)
        {
            // On ties, discard later items/slots so the earliest selected media fills the earliest slots.
            if (best[mediaCursor, slotCursor] == best[mediaCursor - 1, slotCursor])
            {
                mediaCursor--;
                continue;
            }
            if (best[mediaCursor, slotCursor] == best[mediaCursor, slotCursor - 1])
            {
                slotCursor--;
                continue;
            }

            var media = selected[mediaCursor - 1];
            var slot = Slots[slotCursor - 1];
            slot.Media = media;
            assigned++;
            mediaCursor--;
            slotCursor--;
        }

        Changed();
        if (selected.Length == 0)
        {
            Status = "Đã bỏ chọn media; các vị trí trong mẫu đã được xóa.";
            return;
        }

        var missingSlots = Slots.Where(slot => slot.Media is null && (slot.Rule.Required || slot.Rule.MissingSlotPolicy == "error")).ToArray();
        var missingRequired = missingSlots.Length;
        var unusedItems = selected.Where(item => !Slots.Any(slot => slot.Media == item)).ToArray();
        var unused = unusedItems.Length;
        var missingDetail = missingSlots.Length == 0 ? "" : $"Còn {missingSlots.Length} vị trí; tiếp theo: khung {missingSlots[0].Index}.";
        var mismatchDetails = unusedItems.Select(item =>
        {
            var selectedIndex = Array.IndexOf(selected, item) + 1;
            var closestFailure = Slots
                .Select(slot => (Slot: slot, Error: GetAssignmentError(slot, item)))
                .Where(candidate => candidate.Error is not null)
                .OrderBy(candidate => Math.Abs(candidate.Slot.Index - selectedIndex))
                .FirstOrDefault();
            return closestFailure.Error is not null
                ? $"Media #{selectedIndex} ({item.Media.FileName}) không khớp vị trí {closestFailure.Slot.Index}: {closestFailure.Error}"
                : $"Media #{selectedIndex} ({item.Media.FileName}) chưa ghép được với vị trí theo thứ tự đã chọn";
        }).ToArray();
        var mismatchDetail = mismatchDetails.Length == 0 ? "" : " " + mismatchDetails[0] +
            (mismatchDetails.Length > 1 ? $" (và {mismatchDetails.Length - 1} media khác)" : "");
        Status = missingRequired > 0
            ? missingDetail +
              mismatchDetail + (unused > 0 ? " Hãy thay media chưa khớp hoặc đổi thứ tự chọn." : "")
            : $"Đã tự gán {assigned}/{selected.Length} media theo thứ tự." +
              (unused > 0 ? mismatchDetail : "");
    }

    private string? GetAssignmentError(SelectionSlot slot, SelectionMediaItem item)
    {
        var rule = slot.Rule;
        if (!rule.AllowedMediaKinds.Contains(item.Media.Kind))
        {
            if (slot.Rule.SlotId.Contains("group-", StringComparison.Ordinal)
                && slot.Rule.SlotId.Contains("overlay", StringComparison.Ordinal))
                return $"Vị trí {slot.Index} là ảnh phủ, chỉ nhận ảnh.";
            if (slot.Rule.SlotId.Contains("group-", StringComparison.Ordinal))
                return $"Vị trí {slot.Index} là nền, nhận ảnh hoặc video.";
            return $"Vị trí {slot.Index} cần {string.Join("/", rule.AllowedMediaKinds)}.";
        }
        if (slot.Rule.SlotId.Contains("background", StringComparison.Ordinal)
            && item.Media.Kind == "video" && (item.Media.DurationMs ?? 0) <= 0)
            return $"Video nền ở vị trí {slot.Index} cần có thời lượng hợp lệ.";
        var minimumVideoDurationMs = rule.DurationMs;
        if (IsReferenceTimingFallDiary && slot.Rule.SlotId.Contains("background", StringComparison.Ordinal))
            minimumVideoDurationMs = slot.Index == 1
                ? FallDiaryFirstBackgroundDurationMs
                : FallDiarySubsequentBackgroundDurationMs;
        if (item.Media.Kind == "video" && (item.Media.DurationMs ?? 0) < minimumVideoDurationMs)
            return $"Video ở vị trí {slot.Index} cần dài ít nhất {minimumVideoDurationMs / 1000.0:0.#} giây.";
        return null;
    }

    private void ResizeFallDiarySlots(int count)
    {
        count = Math.Clamp(count, 1, FallDiaryMaxMedia);
        while (Slots.Count > count) Slots.RemoveAt(Slots.Count - 1);
        while (Slots.Count < count)
        {
            var requirement = Template.MediaSlotRequirements[Slots.Count];
            var activeRule = new VideoTemplateMediaSlotRequirementDto
            {
                SlotId = requirement.SlotId,
                AllowedMediaKinds = [.. requirement.AllowedMediaKinds],
                Required = true,
                ReusePolicy = requirement.ReusePolicy,
                MissingSlotPolicy = "error",
                DurationMs = requirement.DurationMs,
            };
            Slots.Add(new SelectionSlot(Slots.Count + 1, activeRule));
        }
        OnPropertyChanged(nameof(Heading));
    }

    public Dictionary<string, string> BuildBindings() => Slots.Where(s => s.Media is not null).ToDictionary(s => s.Rule.SlotId, s => s.Media!.Media.AssetId);
    private string? ValidateBindings() => Slots.Any(s => s.Media is null && (s.Rule.Required || s.Rule.MissingSlotPolicy == "error")) ? "Chưa gán đủ vị trí bắt buộc." : null;
    private async Task PrepareAsync()
    {
        if (ValidateBindings() is { } validationError) { Status = validationError; return; }
        IsBusy = true; PreparedPayload = null;
        try { PreparedPayload = await _service.PrepareAsync(Request.TemplateId, Template.TemplateDefinitionVersion!, BuildBindings()); Status = "Payload đã được backend xác thực, sẵn sàng chuyển Template Compiler. Chưa tạo project hoặc render video."; }
        catch (Exception error) { Status = $"Payload chưa hợp lệ: {error.Message}"; }
        finally { IsBusy = false; }
    }

    private async Task ContinueAsync()
    {
        await PrepareAsync();
        if (PreparedPayload is null || (_continueToProcessing is null && _applyMediaReplacement is null)) return;
        IsBusy = true;
        try
        {
            if (_applyMediaReplacement is not null)
            {
                Status = "Payload đã được xác thực. Đang cập nhật media trong bản nháp hiện tại...";
                await _applyMediaReplacement(Request, Template.TemplateDefinitionVersion!, BuildBindings());
            }
            else
            {
                Status = "Payload đã được xác thực. Đang khởi tạo tác vụ áp dụng mẫu...";
                await _continueToProcessing!(Request, Template.TemplateDefinitionVersion!, BuildBindings());
            }
        }
        catch (Exception error)
        {
            Status = $"Không thể bắt đầu xử lý: {error.Message}. Lựa chọn media vẫn được giữ lại.";
        }
        finally { IsBusy = false; }
    }
    private void Changed()
    {
        for (var i = 0; i < Selected.Count; i++)
        {
            var item = Selected[i];
            item.Order = i + 1;
            var slot = Slots.FirstOrDefault(candidate => ReferenceEquals(candidate.Media, item));
            item.SlotLabel = slot?.ShortLabel ?? "Chưa dùng";
        }
        PreparedPayload = null; OnPropertyChanged(nameof(SelectionSummary)); OnPropertyChanged(nameof(Heading)); RefreshCommands();
        ApplyFilter();
        ScheduleStoryPreview();
    }
    /// <summary>
    /// Drag and drop from the library (or within the selected strip) onto a
    /// selected item: a new item replaces it in the same position; an item that
    /// is already selected swaps places with it.
    /// </summary>
    public void DropOnSelected(SelectionMediaItem item, SelectionMediaItem target)
    {
        if (IsBusy || ReferenceEquals(item, target) || !_library.Contains(item)) return;
        var targetIndex = Selected.IndexOf(target);
        if (targetIndex < 0) { DropAtEnd(item); return; }
        var sourceIndex = Selected.IndexOf(item);
        if (sourceIndex >= 0)
        {
            Selected[targetIndex] = item;
            Selected[sourceIndex] = target;
            Status = $"Đã đổi chỗ ảnh {sourceIndex + 1} và ảnh {targetIndex + 1}.";
        }
        else
        {
            target.Order = 0;
            Selected[targetIndex] = item;
            Status = $"Đã thay ảnh số {targetIndex + 1} bằng {item.Media.FileName}.";
        }
        ActiveMedia = item;
        var message = Status;
        AssignSelectionInOrder();
        ShowStoryPageOf(item);
        if (Slots.All(slot => slot.Media is not null || !(slot.Rule.Required || slot.Rule.MissingSlotPolicy == "error")))
            Status = message;
    }

    /// <summary>
    /// Drop one or several media: onto a selected item (one replaces/swaps it,
    /// several are inserted at its position) or onto the strip (added at the end).
    /// </summary>
    public void DropMany(IReadOnlyList<SelectionMediaItem> items, SelectionMediaItem? target)
    {
        if (IsBusy) return;
        var list = items.Where(_library.Contains).Distinct().ToList();
        if (list.Count == 0) return;
        if (list.Count == 1)
        {
            if (target is null) DropAtEnd(list[0]); else DropOnSelected(list[0], target);
            SetLibraryMarks([]);
            return;
        }
        var insertAt = target is null ? Selected.Count : Selected.IndexOf(target);
        if (insertAt < 0) insertAt = Selected.Count;
        foreach (var item in list)
        {
            var index = Selected.IndexOf(item);
            if (index < 0) continue;
            Selected.RemoveAt(index);
            if (index < insertAt) insertAt--;
        }
        if (IsDynamicFallDiary)
        {
            var room = FallDiaryMaxMedia - Selected.Count;
            if (room < list.Count)
            {
                list = list.Take(Math.Max(0, room)).ToList();
                Status = $"Fall Diary chỉ nhận tối đa {FallDiaryMaxMedia} media cho mỗi video.";
            }
        }
        foreach (var item in list) Selected.Insert(insertAt++, item);
        if (list.Count == 0) return;
        ActiveMedia = list[^1];
        AssignSelectionInOrder();
        ShowStoryPageOf(list[^1]);
        SetLibraryMarks([]);
    }

    /// <summary>Drop onto the strip itself: add at the end, or move an already selected item to the end.</summary>
    public void DropAtEnd(SelectionMediaItem item)
    {
        if (IsBusy || !_library.Contains(item)) return;
        var index = Selected.IndexOf(item);
        if (index < 0) { Toggle(item); return; }
        if (index == Selected.Count - 1) return;
        Selected.Move(index, Selected.Count - 1);
        ActiveMedia = item;
        AssignSelectionInOrder();
    }

    public bool IsFilterAll => _filter == "all";
    public bool IsFilterImage => _filter == "image";
    public bool IsFilterVideo => _filter == "video";
    public bool HasActiveMedia => ActiveMedia is not null;

    private VideoTemplateMediaSlotRequirementDto? NextMediaRule =>
        Slots.FirstOrDefault(slot => slot.Media is null)?.Rule
        ?? (IsDynamicFallDiary ? Template.MediaSlotRequirements.ElementAtOrDefault(Selected.Count) : null);

    public string LibraryRuleHint => NextMediaRule is { } rule
        ? $"{rule.SlotId} · {string.Join(" / ", rule.AllowedMediaKinds.Select(kind => kind == "image" ? "Ảnh" : "Video"))}"
        : "Đã đủ khung · kéo media để thay thế";
    public bool IsLibraryEmpty => Media.Count == 0;
    public string EmptyLibraryMessage => "Không có media phù hợp với loại lọc và vị trí đang thêm.";

    private void ApplyFilter()
    {
        var allowedKinds = NextMediaRule?.AllowedMediaKinds
            ?? Template.MediaSlotRequirements.SelectMany(slot => slot.AllowedMediaKinds).Distinct().ToList();
        Media.Clear();
        foreach (var item in _library.Where(item => allowedKinds.Contains(item.Media.Kind)
            && (_filter == "all" || item.Media.Kind == _filter)).Reverse()) Media.Add(item);
        foreach (var item in _library.Where(item => !Media.Contains(item))) item.IsLibraryMarked = false;
        NotifyLibraryMarks();
        OnPropertyChanged(nameof(LibraryRuleHint));
        OnPropertyChanged(nameof(IsLibraryEmpty));
    }
    private void RefreshCommands() { ImportCommand?.NotifyCanExecuteChanged(); ReloadCommand?.NotifyCanExecuteChanged(); PrepareCommand?.NotifyCanExecuteChanged(); ContinueCommand?.NotifyCanExecuteChanged(); ToggleCommand?.NotifyCanExecuteChanged(); LibraryToggleCommand?.NotifyCanExecuteChanged(); AddToSelectionCommand?.NotifyCanExecuteChanged(); AssignCommand?.NotifyCanExecuteChanged(); RemoveBindingCommand?.NotifyCanExecuteChanged(); ClearCommand?.NotifyCanExecuteChanged(); DeleteLibraryCommand?.NotifyCanExecuteChanged(); MarkAllLibraryCommand?.NotifyCanExecuteChanged(); }
}

public sealed class SelectionMediaItem(VideoMediaDto media) : ObservableObject
{
    private bool _isLibraryMarked;
    public bool IsLibraryMarked { get => _isLibraryMarked; set => SetProperty(ref _isLibraryMarked, value); }
    private bool _isDragging;
    /// <summary>True while this media is being dragged (dimmed in the library and strip).</summary>
    public bool IsDragging { get => _isDragging; set => SetProperty(ref _isDragging, value); }
    private int _order;
    private string _slotLabel = "";
    public VideoMediaDto Media { get; } = media;
    /// <summary>Where this item lands in the template, e.g. "Trang 2 · trên".</summary>
    public string SlotLabel { get => _slotLabel; set => SetProperty(ref _slotLabel, value); }
    public BitmapImage? Thumbnail { get; set; }
    public string ThumbnailProblem { get; set; } = "";
    public int Order { get => _order; set { SetProperty(ref _order, value); OnPropertyChanged(nameof(SelectionLabel)); OnPropertyChanged(nameof(IsSelected)); } }
    public bool IsSelected => Order > 0;
    public string TypeText => Media.Kind == "video" ? "Video" : "Ảnh";
    public string ResolutionText => Media.Width is > 0 && Media.Height is > 0 ? $"{Media.Width} × {Media.Height}" : "Chưa rõ độ phân giải";
    public string SizeText => Media.ByteSize >= 1024 * 1024
        ? $"{Media.ByteSize / 1024d / 1024d:0.0} MB"
        : $"{Math.Max(1, Media.ByteSize / 1024)} KB";
    public string DurationBadge => Media.Kind == "video" && Media.DurationMs is > 0 ? $"{Media.DurationMs / 1000.0:0.0}s" : "";
    public bool IsVideo => Media.Kind == "video";
    public string SelectionLabel => Order > 0 ? $"✓ {Order}" : "+";
    public string Caption => Media.Kind == "video" ? $"Video · {Media.DurationMs / 1000.0:0.#}s" : "Ảnh";
}

public sealed class StoryPageDot(int page, bool isCurrent) : ObservableObject
{
    private bool _isCurrent = isCurrent;
    public int Page { get; } = page;
    public bool IsCurrent { get => _isCurrent; set => SetProperty(ref _isCurrent, value); }
}

public sealed class SelectionSlot(int index, VideoTemplateMediaSlotRequirementDto rule) : ObservableObject
{
    private SelectionMediaItem? _media;
    public int Index { get; } = index;
    public VideoTemplateMediaSlotRequirementDto Rule { get; } = rule;
    public string Label
    {
        get
        {
            if (Rule.SlotId.StartsWith("group-", StringComparison.Ordinal))
            {
                var group = (Index - 1) / 9 + 1;
                var position = (Index - 1) % 9;
                return position == 0 ? $"{Index}. Nền nhóm {group}" : $"{Index}. Ảnh phủ {group}.{position}";
            }
            if (ShortLabel != Rule.SlotId) return $"{Index}. {ShortLabel}";
            return Rule.DurationMs > 0
                ? $"{Index}. {Rule.SlotId} · {Rule.DurationMs / 1000.0:0.#}s"
                : $"{Index}. {Rule.SlotId}";
        }
    }
    public SelectionMediaItem? Media { get => _media; set => SetProperty(ref _media, value); }

    /// <summary>Human label for a slot id; story slots read "Trang 2 · ảnh 1".</summary>
    public string ShortLabel
    {
        get
        {
            var match = System.Text.RegularExpressions.Regex.Match(Rule.SlotId, @"^page-(\d+)-photo-(\d+)$");
            if (match.Success)
                return $"Trang {int.Parse(match.Groups[1].Value)} · ảnh {int.Parse(match.Groups[2].Value)}";
            if (Rule.SlotId.StartsWith("group-", StringComparison.Ordinal))
            {
                var group = (Index - 1) / 9 + 1;
                var position = (Index - 1) % 9;
                return position == 0 ? $"Nền nhóm {group}" : $"Ảnh phủ {group}.{position}";
            }
            return Rule.SlotId;
        }
    }
}
