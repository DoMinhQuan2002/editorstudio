using System.Collections.ObjectModel;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public sealed class VideoCreatorGalleryViewModel : ObservableObject
{
    private static readonly string[] PreferredCategoryOrder = ["Xu hướng", "Story", "Carousel", "Cut Out", "Du lịch"];
    private readonly ObservableCollection<VideoTemplateCardViewModel> _templates = [];
    private string _searchText = "";
    private string _selectedCategory = "Tất cả";
    private VideoTemplateCardViewModel? _selectedTemplate;
    private bool _isLoading;
    private bool _hasLoaded;
    private string _catalogStatus = "Danh mục mẫu chưa được tải.";
    private readonly TemplateCatalogService? _catalogService;
    private bool _catalogLoadFailed;
    private VideoCreatorTemplateDetailsViewModel? _currentDetails;
    private readonly IMediaSelectionService? _mediaService;
    private readonly ITemplateProcessingService? _processingService;
    private readonly IVideoCreatorDraftPreviewService? _draftPreviewService;
    private readonly IVideoCreatorExportService? _exportService;
    private readonly IVideoCreatorExportUi _exportUi;
    private readonly IMediaFilePicker _mediaPicker;
    private readonly Dictionary<string, MediaSelectionViewModel> _sessions = new(StringComparer.Ordinal);
    private MediaSelectionViewModel? _currentSelection;
    private VideoCreatorProcessingViewModel? _currentProcessing;
    private VideoCreatorDraftPreviewViewModel? _currentDraftPreview;
    private VideoCreatorExportViewModel? _currentExport;
    private StoryResultViewModel? _currentStoryResult;
    private readonly IStoryTemplateService? _storyService;
    /// <summary>Result screen of a photo story (image-set) template.</summary>
    public StoryResultViewModel? CurrentStoryResult { get => _currentStoryResult; private set => SetProperty(ref _currentStoryResult, value); }
    private VideoProjectDto? _latestSavedDraft;
    private bool _isOpeningDraft;
    public MediaSelectionViewModel? CurrentSelection { get => _currentSelection; private set => SetProperty(ref _currentSelection, value); }
    public VideoCreatorProcessingViewModel? CurrentProcessing { get => _currentProcessing; private set => SetProperty(ref _currentProcessing, value); }
    public VideoCreatorDraftPreviewViewModel? CurrentDraftPreview { get => _currentDraftPreview; private set => SetProperty(ref _currentDraftPreview, value); }
    public VideoCreatorExportViewModel? CurrentExport { get => _currentExport; private set => SetProperty(ref _currentExport, value); }
    public AsyncRelayCommand OpenLatestDraftCommand { get; }
    public bool HasLatestSavedDraft => _latestSavedDraft is not null;
    public string LatestSavedDraftLabel => _latestSavedDraft is null
        ? "Chưa có bản nháp template đã lưu"
        : $"Mở bản nháp gần nhất · {_latestSavedDraft.Title} · r{_latestSavedDraft.Revision}";
    public bool IsOpeningDraft { get => _isOpeningDraft; private set { if (SetProperty(ref _isOpeningDraft, value)) OpenLatestDraftCommand.NotifyCanExecuteChanged(); } }
    public async Task OpenMediaSelectionAsync(MediaSelectionSessionRequest request)
    {
        var template = _templates.FirstOrDefault(t => t.TemplateId == request.TemplateId)?.Template;
        if (_mediaService is null || !MediaSelectionViewModel.IsEligible(template)) return;
        if (!_sessions.TryGetValue(request.TemplateId, out var session)
            || session.Template.TemplateDefinitionVersion != template!.TemplateDefinitionVersion)
        {
            request = request with { SelectionSessionId = string.IsNullOrWhiteSpace(request.SelectionSessionId)
                ? Guid.NewGuid().ToString("N") : request.SelectionSessionId };
            session = new MediaSelectionViewModel(template!, request, _mediaService, _mediaPicker,
                () => CurrentSelection = null, ContinueToProcessingAsync, storyService: _storyService);
            _sessions[request.TemplateId] = session;
        }
        else
        {
            request = session.Request;
        }
        CurrentProcessing = null;
        CurrentExport = null;
        CurrentDraftPreview = null;
        CurrentStoryResult = null;
        CurrentSelection = session;
        await session.LoadAsync();
    }

    public ObservableCollection<VideoTemplateCategoryViewModel> Categories { get; } = [];
    public ObservableCollection<VideoTemplateCardViewModel> VisibleTemplates { get; } = [];
    public RelayCommand SelectCategoryCommand { get; }
    public RelayCommand SelectTemplateCommand { get; }
    public RelayCommand UseTemplateCommand { get; }
    public AsyncRelayCommand RetryLoadCommand { get; }

    public VideoCreatorGalleryViewModel(TemplateCatalogService? catalogService = null, IMediaSelectionService? mediaService = null,
        IMediaFilePicker? mediaPicker = null, ITemplateProcessingService? processingService = null,
        IVideoCreatorDraftPreviewService? draftPreviewService = null,
        IVideoCreatorExportService? exportService = null,
        IVideoCreatorExportUi? exportUi = null,
        IStoryTemplateService? storyService = null)
    {
        _storyService = storyService;
        _catalogService = catalogService;
        _mediaService = mediaService;
        _processingService = processingService;
        _draftPreviewService = draftPreviewService;
        _exportService = exportService;
        _exportUi = exportUi ?? new WpfVideoCreatorExportUi();
        _mediaPicker = mediaPicker ?? new WpfMediaFilePicker();
        SelectCategoryCommand = new RelayCommand(value =>
        {
            if (value is string category) SelectedCategory = category;
        });
        SelectTemplateCommand = new RelayCommand(value =>
        {
            if (value is VideoTemplateCardViewModel template) SelectedTemplate = template;
        });
        UseTemplateCommand = new RelayCommand(
            value => OpenTemplateDetails(value as string ?? SelectedTemplate?.TemplateId));
        RetryLoadCommand = new AsyncRelayCommand(() => LoadCatalogAsync(forceReload: true),
            _ => !IsLoading && _catalogService is not null);
        OpenLatestDraftCommand = new AsyncRelayCommand(OpenLatestDraftAsync,
            _ => !IsOpeningDraft && _draftPreviewService is not null);
        Categories.Add(new VideoTemplateCategoryViewModel("Tất cả", true));
    }

    public string SearchText
    {
        get => _searchText;
        set
        {
            if (!SetProperty(ref _searchText, value)) return;
            UpdateVisibleTemplates();
        }
    }

    public string SelectedCategory
    {
        get => _selectedCategory;
        set
        {
            if (!SetProperty(ref _selectedCategory, value)) return;
            foreach (var category in Categories) category.IsSelected = category.Name == value;
            UpdateVisibleTemplates();
        }
    }

    public VideoTemplateCardViewModel? SelectedTemplate
    {
        get => _selectedTemplate;
        set
        {
            if (ReferenceEquals(_selectedTemplate, value)) return;
            if (_selectedTemplate is not null) _selectedTemplate.IsSelected = false;
            _selectedTemplate = value;
            if (_selectedTemplate is not null) _selectedTemplate.IsSelected = true;
            OnPropertyChanged();
            OnPropertyChanged(nameof(SelectedTemplateName));
            OnPropertyChanged(nameof(SelectedTemplateSummary));
            OnPropertyChanged(nameof(SelectedTemplateHasPoster));
            OnPropertyChanged(nameof(SelectedTemplatePosterPath));
            OnPropertyChanged(nameof(SelectedTemplateCategory));
            OnPropertyChanged(nameof(SelectedTemplateMediaText));
            OnPropertyChanged(nameof(SelectedTemplateDuration));
            OnPropertyChanged(nameof(SelectedTemplateAspect));
            OnPropertyChanged(nameof(SelectedTemplateResolution));
            OnPropertyChanged(nameof(HasSelectedTemplate));
            OnPropertyChanged(nameof(CanUseTemplate));
            UseTemplateCommand?.NotifyCanExecuteChanged();
        }
    }

    public bool IsLoading
    {
        get => _isLoading;
        private set
        {
            if (!SetProperty(ref _isLoading, value)) return;
            OnPropertyChanged(nameof(HasNoVisibleTemplates));
            OnPropertyChanged(nameof(EmptyStateTitle));
            OnPropertyChanged(nameof(EmptyStateDescription));
        }
    }
    public bool HasTemplates => _templates.Count > 0;
    public bool HasNoVisibleTemplates => VisibleTemplates.Count == 0;
    public bool IsCatalogLoadFailed => _catalogLoadFailed;
    public object ActivePage => (object?)CurrentDetails ?? this;
    public VideoCreatorTemplateDetailsViewModel? CurrentDetails
    {
        get => _currentDetails;
        private set
        {
            if (!SetProperty(ref _currentDetails, value)) return;
            OnPropertyChanged(nameof(ActivePage));
            OnPropertyChanged(nameof(IsGalleryVisible));
            OnPropertyChanged(nameof(IsDetailsVisible));
        }
    }
    public bool IsGalleryVisible => CurrentDetails is null;
    public bool IsDetailsVisible => CurrentDetails is not null;
    public string CatalogStatus { get => _catalogStatus; private set => SetProperty(ref _catalogStatus, value); }
    public string SelectedTemplateName => SelectedTemplate?.Name ?? "Chưa chọn mẫu";
    public bool CanUseTemplate => SelectedTemplate is not null;
    public string SelectedTemplateSummary => SelectedTemplate is null
        ? "Chọn một mẫu để xem vị trí media, thời lượng và tỷ lệ khung hình."
        : $"{SelectedTemplate.RequiredMediaSlotsText} · {SelectedTemplate.Duration} · Khung {SelectedTemplate.AspectRatio}";
    public bool SelectedTemplateHasPoster => SelectedTemplate?.HasPoster == true;

    // ---- Bottom selection bar (redesign) ----
    public bool HasSelectedTemplate => SelectedTemplate is not null;
    public string? SelectedTemplatePosterPath => SelectedTemplate?.PosterPath;
    public string SelectedTemplateCategory => SelectedTemplate?.Category ?? "";
    public string SelectedTemplateMediaText => SelectedTemplate?.RequiredMediaSlotsText ?? "";
    public string SelectedTemplateDuration => SelectedTemplate?.Duration ?? "";
    public string SelectedTemplateAspect => SelectedTemplate is null ? "" : $"Khung {SelectedTemplate.AspectRatio}";
    public string SelectedTemplateResolution => SelectedTemplate is null ? ""
        : $"{SelectedTemplate.Template.Width} × {SelectedTemplate.Template.Height}";

    // ---- Grid / list toggle ----
    private bool _isListView;
    public bool IsListView
    {
        get => _isListView;
        set { if (SetProperty(ref _isListView, value)) OnPropertyChanged(nameof(IsGridView)); }
    }
    public bool IsGridView => !IsListView;
    public RelayCommand ShowGridCommand => _showGridCommand ??= new RelayCommand(_ => IsListView = false);
    public RelayCommand ShowListCommand => _showListCommand ??= new RelayCommand(_ => IsListView = true);
    private RelayCommand? _showGridCommand;
    private RelayCommand? _showListCommand;
    public string EmptyStateTitle => IsLoading ? "Đang tải danh mục mẫu…"
        : _catalogLoadFailed ? "Không thể tải mẫu video"
        : _templates.Count == 0 ? "Chưa có mẫu video"
        : "Không tìm thấy mẫu phù hợp";
    public string EmptyStateDescription => IsLoading ? "Đang đọc danh mục mẫu từ backend."
        : _catalogLoadFailed ? "Kiểm tra kết nối backend rồi mở lại màn hình Video Editor."
        : _templates.Count == 0 ? "Catalog hiện chưa có mẫu video để hiển thị."
        : "Thử từ khóa khác hoặc chọn danh mục khác.";

    public Task LoadCatalogAsync(CancellationToken cancellationToken = default) =>
        LoadCatalogAsync(forceReload: false, cancellationToken);

    private async Task LoadCatalogAsync(bool forceReload, CancellationToken cancellationToken = default)
    {
        if ((!forceReload && _hasLoaded) || IsLoading) return;
        _hasLoaded = true;
        if (_catalogService is null)
        {
            _catalogLoadFailed = true;
            CatalogStatus = "Backend chưa kết nối. Không thể tải danh mục mẫu.";
            OnPropertyChanged(nameof(IsCatalogLoadFailed));
            OnPropertyChanged(nameof(HasNoVisibleTemplates));
            OnPropertyChanged(nameof(EmptyStateTitle));
            OnPropertyChanged(nameof(EmptyStateDescription));
            RetryLoadCommand.NotifyCanExecuteChanged();
            return;
        }

        var selectedTemplateId = SelectedTemplate?.TemplateId;
        var selectedCategory = SelectedCategory;
        _catalogLoadFailed = false;
        IsLoading = true;
        RetryLoadCommand.NotifyCanExecuteChanged();
        CatalogStatus = "Đang tải danh mục mẫu từ backend…";
        OnPropertyChanged(nameof(HasNoVisibleTemplates));
        try
        {
            var items = await _catalogService.GetTemplatesAsync(cancellationToken);
            _templates.Clear();
            VisibleTemplates.Clear();
            Categories.Clear();
            Categories.Add(new VideoTemplateCategoryViewModel("Tất cả", true));
            foreach (var item in items)
                _templates.Add(new VideoTemplateCardViewModel(item));

            var categories = _templates.Select(template => template.Category)
                .Where(category => !string.IsNullOrWhiteSpace(category))
                .Distinct(StringComparer.CurrentCultureIgnoreCase)
                .ToArray();
            foreach (var category in categories.OrderBy(CategoryOrder).ThenBy(value => value, StringComparer.CurrentCultureIgnoreCase))
                Categories.Add(new VideoTemplateCategoryViewModel(category));

            SelectedCategory = categories.Contains(selectedCategory, StringComparer.CurrentCultureIgnoreCase)
                ? selectedCategory
                : "Tất cả";
            foreach (var category in Categories)
                category.IsSelected = category.Name == SelectedCategory;
            SelectedTemplate = selectedTemplateId is null
                ? null
                : _templates.FirstOrDefault(template => template.TemplateId == selectedTemplateId);
            UpdateVisibleTemplates();
            await RefreshLatestSavedDraftAsync(cancellationToken);
            CatalogStatus = items.Count == 0
                ? "Backend chưa có mẫu video nào trong catalog."
                : $"Đã tải {items.Count} mẫu từ catalog · poster và video xem trước chưa được cung cấp.";
        }
        catch (Exception error)
        {
            _catalogLoadFailed = true;
            if (_templates.Count == 0)
            {
                VisibleTemplates.Clear();
                Categories.Clear();
                Categories.Add(new VideoTemplateCategoryViewModel("Tất cả", true));
                SelectedTemplate = null;
                CatalogStatus = $"Không tải được catalog mẫu. {error.Message}";
            }
            else
            {
                CatalogStatus = $"Không thể làm mới catalog. Đang giữ dữ liệu đã tải trước đó. {error.Message}";
            }
            OnPropertyChanged(nameof(IsCatalogLoadFailed));
            OnPropertyChanged(nameof(EmptyStateTitle));
            OnPropertyChanged(nameof(EmptyStateDescription));
        }
        finally
        {
            IsLoading = false;
            OnPropertyChanged(nameof(HasTemplates));
            OnPropertyChanged(nameof(HasNoVisibleTemplates));
            OnPropertyChanged(nameof(IsCatalogLoadFailed));
            OnPropertyChanged(nameof(EmptyStateTitle));
            OnPropertyChanged(nameof(EmptyStateDescription));
            RetryLoadCommand.NotifyCanExecuteChanged();
        }
    }

    public void OpenTemplateDetails(string? templateId)
    {
        var requestedId = templateId?.Trim();
        var template = string.IsNullOrWhiteSpace(requestedId)
            ? null
            : _templates.FirstOrDefault(item => string.Equals(item.TemplateId, requestedId, StringComparison.Ordinal));

        if (template is null)
        {
            CurrentDetails = VideoCreatorTemplateDetailsViewModel.CreateError(
                requestedId,
                string.IsNullOrWhiteSpace(requestedId)
                    ? "Chưa có mã mẫu để mở. Hãy quay lại danh sách và chọn một mẫu trong catalog."
                    : $"Không tìm thấy mẫu có mã “{requestedId}” trong catalog hiện tại.",
                GoBackToGallery,
                _catalogService is null ? null : () => RetryTemplateDetailsAsync(requestedId));
            return;
        }

        SelectedTemplate = template;
        CurrentDetails = new VideoCreatorTemplateDetailsViewModel(
            template.Template,
            GoBackToGallery,
            () => RetryTemplateDetailsAsync(template.TemplateId),
            _mediaService is null ? null : OpenMediaSelectionAsync);
    }

    private async Task RetryTemplateDetailsAsync(string? templateId)
    {
        await LoadCatalogAsync(forceReload: true);
        if (_catalogLoadFailed)
        {
            CurrentDetails = VideoCreatorTemplateDetailsViewModel.CreateError(
                templateId,
                "Chưa thể tải lại danh mục mẫu. Kiểm tra kết nối backend rồi thử lại.",
                GoBackToGallery,
                () => RetryTemplateDetailsAsync(templateId));
            return;
        }
        OpenTemplateDetails(templateId);
    }

    private void GoBackToGallery() => CurrentDetails = null;

    /// <summary>Leaves the template flow (details, media, processing, editing, export) and shows the template gallery.</summary>
    public void ReturnToGallery() => GoBackToGallery();

    private async Task ContinueToProcessingAsync(
        MediaSelectionSessionRequest request, string templateVersion, Dictionary<string, string> bindings)
    {
        if (_processingService is null)
            throw new InvalidOperationException("Processing service chưa được kết nối.");
        if (!_sessions.TryGetValue(request.TemplateId, out var selectionSession))
            throw new InvalidOperationException("Không tìm thấy phiên chọn media hiện tại.");

        // Photo story templates output images; they skip the video pipeline.
        if (selectionSession.Template.IsImageSet)
        {
            if (_storyService is null)
                throw new InvalidOperationException("Dịch vụ dựng ảnh story chưa được kết nối.");
            var story = new StoryResultViewModel(_storyService, selectionSession.Template, templateVersion, bindings,
                () =>
                {
                    CurrentStoryResult = null;
                    CurrentSelection = selectionSession;
                });
            CurrentSelection = null;
            CurrentProcessing = null;
            CurrentDraftPreview = null;
            CurrentExport = null;
            CurrentStoryResult = story;
            await story.RenderAsync();
            return;
        }

        var processing = new VideoCreatorProcessingViewModel(
            _processingService, request, templateVersion, bindings,
            () =>
            {
                CurrentProcessing = null;
                CurrentExport = null;
                CurrentSelection = selectionSession;
                CurrentDraftPreview = null;
            },
            OpenDraftPreviewAsync);
        CurrentSelection = null;
        CurrentDraftPreview = null;
        CurrentExport = null;
        CurrentProcessing = processing;
        await processing.StartAsync();
    }

    private async Task OpenDraftPreviewAsync(VideoCreatorProcessingViewModel processing)
    {
        if (_draftPreviewService is null || !processing.IsSucceeded || string.IsNullOrWhiteSpace(processing.DraftProjectId))
            return;
        var card = _templates.FirstOrDefault(item => item.TemplateId == processing.TemplateId);
        var definitionAvailable = card is not null
            && card.Template.TemplateDefinitionVersion == processing.TemplateVersion;
        var preview = new VideoCreatorDraftPreviewViewModel(
            _draftPreviewService, processing.DraftProjectId, processing.TemplateId,
            processing.TemplateVersion,
            () => CurrentDraftPreview = null,
            _mediaService is null ? null : OpenMediaReplacement,
            definitionAvailable,
            OpenExport);
        CurrentDraftPreview = preview;
        await preview.LoadAsync();
    }

    private async Task OpenLatestDraftAsync()
    {
        if (_draftPreviewService is null || IsOpeningDraft) return;
        IsOpeningDraft = true;
        try
        {
            await RefreshLatestSavedDraftAsync();
            if (_latestSavedDraft is null)
            {
                CatalogStatus = "Chưa tìm thấy bản nháp template có metadata và media bindings hợp lệ.";
                return;
            }
            var version = ReadMetadataString(_latestSavedDraft, "templateDefinitionVersion")!;
            var currentTemplate = _templates.FirstOrDefault(item => item.TemplateId == _latestSavedDraft.TemplateId);
            var definitionAvailable = currentTemplate is not null
                && currentTemplate.Template.TemplateDefinitionVersion == version;
            var preview = new VideoCreatorDraftPreviewViewModel(
                _draftPreviewService, _latestSavedDraft.ProjectId, _latestSavedDraft.TemplateId, version,
                () => CurrentDraftPreview = null,
                _mediaService is null ? null : OpenMediaReplacement,
                definitionAvailable,
                OpenExport);
            CurrentDetails = null;
            CurrentSelection = null;
            CurrentProcessing = null;
            CurrentExport = null;
            CurrentDraftPreview = preview;
            await preview.LoadAsync();
        }
        catch (Exception error)
        {
            CatalogStatus = $"Không thể mở bản nháp đã lưu: {error.Message}";
        }
        finally { IsOpeningDraft = false; }
    }

    private async Task RefreshLatestSavedDraftAsync(CancellationToken cancellationToken = default)
    {
        if (_draftPreviewService is null) return;
        try
        {
            var projects = await _draftPreviewService.GetProjectsAsync(cancellationToken);
            _latestSavedDraft = projects
                .Where(project => project.SchemaVersion == 2
                    && !string.IsNullOrWhiteSpace(ReadMetadataString(project, "templateDefinitionVersion"))
                    && ReadMetadataStringMap(project, "templateBindings").Count > 0)
                .OrderByDescending(project => project.UpdatedAt)
                .FirstOrDefault();
        }
        catch { _latestSavedDraft = null; }
        OnPropertyChanged(nameof(HasLatestSavedDraft));
        OnPropertyChanged(nameof(LatestSavedDraftLabel));
        OpenLatestDraftCommand?.NotifyCanExecuteChanged();
    }

    private void OpenMediaReplacement(VideoCreatorDraftPreviewViewModel preview)
    {
        if (_mediaService is null || !preview.CanReplaceMedia) return;
        var card = _templates.FirstOrDefault(item => item.TemplateId == preview.TemplateId);
        if (card is null || card.Template.TemplateDefinitionVersion != preview.TemplateVersion) return;

        var request = new MediaSelectionSessionRequest(preview.TemplateId, Guid.NewGuid().ToString("N"));
        MediaSelectionViewModel? selection = null;
        selection = new MediaSelectionViewModel(
            card.Template, request, _mediaService, _mediaPicker,
            () => CurrentSelection = null,
            applyMediaReplacement: async (_, _, bindings) =>
            {
                await preview.ReplaceMediaAsync(bindings);
                await selection!.ApplyBindingsAsync(preview.MediaBindings);
                CurrentSelection = null;
                await RefreshLatestSavedDraftAsync();
            });
        _sessions[preview.TemplateId] = selection;
        CurrentDraftPreview = preview;
        _ = LoadReplacementSelectionAsync(selection, preview);
    }

    private void OpenExport(Screen6DraftHandoff handoff)
    {
        if (_exportService is null || CurrentDraftPreview is null) return;
        var export = new VideoCreatorExportViewModel(_exportService, _exportUi, handoff,
            () => CurrentExport = null);
        CurrentExport = export;
        _ = export.LoadAsync();
    }

    private async Task LoadReplacementSelectionAsync(
        MediaSelectionViewModel selection, VideoCreatorDraftPreviewViewModel preview)
    {
        await selection.LoadAsync();
        try { await selection.ApplyBindingsAsync(preview.MediaBindings); }
        catch (Exception error) { selection.SetStatus($"Không thể khôi phục binding: {error.Message}"); }
        CurrentSelection = selection;
    }

    private static string? ReadMetadataString(VideoProjectDto project, string key)
    {
        if (!project.TemplateMetadata.TryGetValue(key, out var value)) return null;
        return value switch
        {
            string text => text,
            System.Text.Json.JsonElement { ValueKind: System.Text.Json.JsonValueKind.String } json => json.GetString(),
            _ => null,
        };
    }

    private static Dictionary<string, string> ReadMetadataStringMap(VideoProjectDto project, string key)
    {
        if (!project.TemplateMetadata.TryGetValue(key, out var value)) return new(StringComparer.Ordinal);
        if (value is System.Text.Json.JsonElement { ValueKind: System.Text.Json.JsonValueKind.Object } json)
        {
            var result = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var item in json.EnumerateObject())
                if (item.Value.ValueKind == System.Text.Json.JsonValueKind.String)
                    result[item.Name] = item.Value.GetString() ?? "";
            return result;
        }
        if (value is IDictionary<string, string> map) return new(map, StringComparer.Ordinal);
        return new(StringComparer.Ordinal);
    }

    private static int CategoryOrder(string category)
    {
        var index = Array.FindIndex(PreferredCategoryOrder,
            value => string.Equals(value, category, StringComparison.CurrentCultureIgnoreCase));
        return index < 0 ? PreferredCategoryOrder.Length : index;
    }

    private void UpdateVisibleTemplates()
    {
        var query = SearchText.Trim();
        var matches = _templates.Where(template =>
            (SelectedCategory == "Tất cả" || string.Equals(template.Category, SelectedCategory, StringComparison.CurrentCultureIgnoreCase))
            && (query.Length == 0 || template.Name.Contains(query, StringComparison.CurrentCultureIgnoreCase)
                || template.Description.Contains(query, StringComparison.CurrentCultureIgnoreCase)
                || template.Category.Contains(query, StringComparison.CurrentCultureIgnoreCase))).ToArray();
        VisibleTemplates.Clear();
        foreach (var template in matches) VisibleTemplates.Add(template);
        if (SelectedTemplate is not null && !matches.Contains(SelectedTemplate))
            SelectedTemplate = null;
        OnPropertyChanged(nameof(HasNoVisibleTemplates));
        OnPropertyChanged(nameof(EmptyStateTitle));
        OnPropertyChanged(nameof(EmptyStateDescription));
    }
}

public sealed class VideoTemplateCategoryViewModel(string name, bool isSelected = false) : ObservableObject
{
    private bool _isSelected = isSelected;
    public string Name { get; } = name;
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }
}

public sealed class VideoTemplateCardViewModel : ObservableObject
{
    private bool _isSelected;

    public VideoTemplateCardViewModel(VideoTemplateDto template)
    {
        Template = template;
        TemplateId = template.TemplateId;
        Name = template.Name;
        Description = template.Description;
        Category = template.Category;
        Duration = FormatDuration(template.DurationMs);
        SceneCount = template.SceneCount;
        RequiredMediaSlots = Math.Max(0, template.RequiredMediaSlots);
        AspectRatio = template.AspectRatio;
        PreviewAvailable = template.PreviewAvailable;
        PosterPath = template.PosterPath;
        PreviewSource = template.PreviewSource;
        IsNew = template.IsNew;
    }

    public VideoTemplateDto Template { get; }
    public string TemplateId { get; }
    public string Name { get; }
    public string Description { get; }
    public string Category { get; }
    public string Duration { get; }
    public int SceneCount { get; }
    public int RequiredMediaSlots { get; }
    public string RequiredMediaSlotsText => Template.TemplateId == "fall-diary"
        && Template.TemplateDefinitionVersion is "0.6.0-dynamic-batches" or "0.7.0-reference-timing"
            or "0.8.0-intro-title" or "0.9.0-reference-overlays"
            ? "1–36 media theo thứ tự"
            : RequiredMediaSlots > 0
                ? $"{RequiredMediaSlots} vị trí media"
                : "Chưa khai báo vị trí media";
    public string AspectRatio { get; }
    public bool PreviewAvailable { get; }
    public string? PosterPath { get; }
    public string? PreviewSource { get; }
    public bool IsNew { get; }
    public bool HasPoster => !string.IsNullOrWhiteSpace(PosterPath);
    public bool HasNoPoster => !HasPoster;
    public string PreviewStatus => PreviewAvailable ? "Có preview"
        : Template.AvailabilityStatus == "PILOT_RENDERABLE" ? "Pilot · chưa có demo" : "Chưa có preview";
    public string AccessibilityName => $"{Name}, {Category}, {Duration}, {RequiredMediaSlotsText}, khung {AspectRatio}";
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }

    private static string FormatDuration(int milliseconds) =>
        milliseconds <= 0
            ? "Unspecified"
            : TimeSpan.FromMilliseconds(milliseconds).ToString(@"mm\:ss");
}
