using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

/// <summary>
/// Result screen for a photo story template: renders the pages from the chosen
/// photos, shows them, and saves the images where the user wants them.
/// </summary>
public sealed class StoryResultViewModel : ObservableObject
{
    private readonly IStoryTemplateService _service;
    private readonly Action _back;
    private readonly Func<string?> _pickFolder;
    private readonly Dictionary<string, string> _bindings;
    private StoryRenderResultDto? _result;
    private StoryPageViewModel? _selectedPage;
    private bool _isBusy;
    private string _status = "Đang dựng ảnh...";
    private string? _errorMessage;
    private double? _progressPercent;
    private bool _hasFailed;

    public StoryResultViewModel(IStoryTemplateService service, VideoTemplateDto template, string templateVersion,
        Dictionary<string, string> bindings, Action back, Func<string?>? pickFolder = null)
    {
        _service = service;
        Template = template;
        TemplateVersion = templateVersion;
        _bindings = new Dictionary<string, string>(bindings, StringComparer.Ordinal);
        _back = back;
        _pickFolder = pickFolder ?? PickFolderWithDialog;
        BackCommand = new RelayCommand(_ => _back(), _ => !IsBusy);
        RenderCommand = new AsyncRelayCommand(RenderAsync, _ => !IsBusy);
        SaveAllCommand = new RelayCommand(async _ =>
        {
            // Saving the pages is the export step for image templates.
            if (await ExportGate.AllowAsync(Template.TemplateId)) SaveAll();
        }, _ => !IsBusy && Pages.Count > 0);
        OpenFolderCommand = new RelayCommand(_ => OpenFolder(_result?.Directory), _ => _result is not null);
        SelectPageCommand = new RelayCommand(value =>
        {
            if (value is StoryPageViewModel page) SelectedPage = page;
        });
        PreviousPageCommand = new RelayCommand(_ => MovePage(-1), _ => CanMovePage(-1));
        NextPageCommand = new RelayCommand(_ => MovePage(1), _ => CanMovePage(1));
    }

    public VideoTemplateDto Template { get; }
    public string TemplateVersion { get; }
    public string Title => Template.Name;
    public ObservableCollection<StoryPageViewModel> Pages { get; } = [];
    public RelayCommand BackCommand { get; }
    public AsyncRelayCommand RenderCommand { get; }
    public RelayCommand SaveAllCommand { get; }
    public RelayCommand OpenFolderCommand { get; }
    public RelayCommand SelectPageCommand { get; }
    public RelayCommand PreviousPageCommand { get; }
    public RelayCommand NextPageCommand { get; }
    public StoryPageViewModel? SelectedPage
    {
        get => _selectedPage;
        set
        {
            if (_selectedPage is not null) _selectedPage.IsSelected = false;
            if (!SetProperty(ref _selectedPage, value)) return;
            if (value is not null) value.IsSelected = true;
            PreviousPageCommand.NotifyCanExecuteChanged();
            NextPageCommand.NotifyCanExecuteChanged();
        }
    }
    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (!SetProperty(ref _isBusy, value)) return;
            OnPropertyChanged(nameof(IsProcessingScreenVisible));
            BackCommand.NotifyCanExecuteChanged();
            RenderCommand.NotifyCanExecuteChanged();
            SaveAllCommand.NotifyCanExecuteChanged();
            OpenFolderCommand.NotifyCanExecuteChanged();
        }
    }
    public string Status { get => _status; private set => SetProperty(ref _status, value); }

    // ---- Processing screen (same look as the video templates' "Xử lý" step) ----
    public ObservableCollection<StoryStageViewModel> Stages { get; } = [];
    public double? ProgressPercent
    {
        get => _progressPercent;
        private set { if (SetProperty(ref _progressPercent, value)) OnPropertyChanged(nameof(ProgressLabel)); }
    }
    public string ProgressLabel => $"{Math.Round(ProgressPercent ?? 0):0}%";
    /// <summary>True while rendering, and after a failure, so the processing screen stays up with the error.</summary>
    public bool IsProcessingScreenVisible => IsBusy || (HasFailed && Pages.Count == 0);
    public bool HasFailed
    {
        get => _hasFailed;
        private set { if (SetProperty(ref _hasFailed, value)) { OnPropertyChanged(nameof(IsProcessingScreenVisible)); OnPropertyChanged(nameof(Heading)); OnPropertyChanged(nameof(Description)); } }
    }
    public string Heading => HasFailed ? "Chưa thể áp dụng mẫu" : "Đang áp dụng mẫu...";
    public string Description => HasFailed
        ? "Hệ thống chưa dựng xong ảnh. Ảnh bạn đã chọn vẫn được giữ lại."
        : "Hệ thống đang ghép ảnh vào từng trang, thêm chữ và trang trí theo mẫu của bạn.";
    public string? ErrorMessage { get => _errorMessage; private set => SetProperty(ref _errorMessage, value); }

    private bool CanMovePage(int offset)
    {
        if (SelectedPage is null) return false;
        var currentIndex = Pages.IndexOf(SelectedPage);
        return currentIndex >= 0 && currentIndex + offset >= 0 && currentIndex + offset < Pages.Count;
    }

    private void MovePage(int offset)
    {
        if (!CanMovePage(offset) || SelectedPage is null) return;
        SelectedPage = Pages[Pages.IndexOf(SelectedPage) + offset];
    }

    public async Task RenderAsync()
    {
        if (IsBusy) return;
        var pageCount = Math.Max(1, Template.SceneCount);
        Pages.Clear();
        SelectedPage = null;
        HasFailed = false;
        ErrorMessage = null;
        ProgressPercent = 0;
        Stages.Clear();
        var check = new StoryStageViewModel($"Kiểm tra {_bindings.Count} ảnh đã chọn");
        var render = new StoryStageViewModel($"Dựng {pageCount} trang ảnh");
        var finish = new StoryStageViewModel("Chuẩn bị xem trước");
        Stages.Add(check); Stages.Add(render); Stages.Add(finish);
        IsBusy = true;
        Status = $"Đang dựng {pageCount} trang ảnh từ {_bindings.Count} ảnh đã chọn...";
        var runId = Guid.NewGuid().ToString("N")[..12];
        var rendered = new List<StoryRenderPageDto>();
        StoryStageViewModel current = check;
        try
        {
            check.Status = "RUNNING";
            for (var page = 1; page <= pageCount; page++)
            {
                var result = await _service.RenderPageAsync(Template.TemplateId, TemplateVersion, _bindings, page, runId);
                if (page == 1)
                {
                    // The backend validates every photo before drawing the first page.
                    check.Status = "COMPLETED";
                    current = render;
                    render.Status = "RUNNING";
                }
                _result = result;
                rendered.AddRange(result.Pages);
                render.Message = $"Đã dựng {page}/{pageCount} trang";
                ProgressPercent = 5 + 85.0 * page / pageCount;
            }
            render.Status = "COMPLETED";
            current = finish;
            finish.Status = "RUNNING";
            foreach (var page in rendered.OrderBy(page => page.Index))
            {
                if (!File.Exists(page.Path))
                    throw new FileNotFoundException("Không tìm thấy ảnh đã dựng.", page.Path);
                Pages.Add(new StoryPageViewModel(page.Index, page.Path, LoadImage(page.Path, 360), LoadImage(page.Path, 1080)));
            }
            ProgressPercent = 100;
            finish.Status = "COMPLETED";
            SelectedPage = Pages.FirstOrDefault();
            Status = $"Đã dựng {Pages.Count} ảnh 1080×1920. Bấm \"Lưu tất cả ảnh\" để chép vào thư mục bạn chọn.";
        }
        catch (Exception error)
        {
            current.Status = "FAILED";
            current.Message = error.Message;
            Pages.Clear();
            HasFailed = true;
            ErrorMessage = $"Không dựng được ảnh: {error.Message}";
            Status = "Chưa dựng xong. Ảnh bạn đã chọn vẫn được giữ; quay lại hoặc thử lại.";
        }
        finally
        {
            IsBusy = false;
            OnPropertyChanged(nameof(IsProcessingScreenVisible));
            OpenFolderCommand.NotifyCanExecuteChanged();
            SaveAllCommand.NotifyCanExecuteChanged();
        }
    }

    private void SaveAll()
    {
        var folder = _pickFolder();
        if (string.IsNullOrWhiteSpace(folder)) return;
        try
        {
            var stem = string.Concat(Template.Name.Split(Path.GetInvalidFileNameChars())).Replace(' ', '_');
            var stamp = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss");
            foreach (var page in Pages)
            {
                var target = Path.Combine(folder, $"{stem}_{stamp}_{page.Index:00}{Path.GetExtension(page.Path)}");
                File.Copy(page.Path, target, overwrite: false);
            }
            ErrorMessage = null;
            Status = $"Đã lưu {Pages.Count} ảnh vào {folder}.";
            OpenFolder(folder);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            ErrorMessage = $"Không lưu được ảnh: {error.Message}";
        }
    }

    private static string? PickFolderWithDialog()
    {
        var dialog = new Microsoft.Win32.OpenFolderDialog { Title = "Chọn thư mục lưu ảnh story" };
        return dialog.ShowDialog() == true ? dialog.FolderName : null;
    }

    private static void OpenFolder(string? folder)
    {
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try { Process.Start(new ProcessStartInfo("explorer.exe", $"\"{folder}\"") { UseShellExecute = true }); }
        catch (Exception) { /* Opening Explorer is a convenience only. */ }
    }

    private static BitmapImage LoadImage(string path, int decodeWidth)
    {
        var image = new BitmapImage();
        image.BeginInit();
        image.CacheOption = BitmapCacheOption.OnLoad;
        image.DecodePixelWidth = decodeWidth;
        image.UriSource = new Uri(path, UriKind.Absolute);
        image.EndInit();
        image.Freeze();
        return image;
    }
}

public sealed class StoryPageViewModel(int index, string path, BitmapImage thumbnail, BitmapImage image) : ObservableObject
{
    private bool _isSelected;
    public int Index { get; } = index;
    public string Path { get; } = path;
    public string Label { get; } = $"Trang {index}";
    public BitmapImage Thumbnail { get; } = thumbnail;
    public BitmapImage Image { get; } = image;
    public string IndicatorGlyph => IsSelected ? "●" : "○";
    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            if (!SetProperty(ref _isSelected, value)) return;
            OnPropertyChanged(nameof(IndicatorGlyph));
        }
    }
}

/// <summary>One step on the story processing screen.</summary>
public sealed class StoryStageViewModel(string name) : ObservableObject
{
    private string _status = "PENDING";
    private string? _message;
    public string Name { get; } = name;
    /// <summary>PENDING, RUNNING, COMPLETED or FAILED (same values as the video processing stages).</summary>
    public string Status
    {
        get => _status;
        set { if (SetProperty(ref _status, value)) OnPropertyChanged(nameof(Glyph)); }
    }
    public string? Message { get => _message; set => SetProperty(ref _message, value); }
    public string Glyph => Status switch { "COMPLETED" => "✓", "FAILED" => "!", _ => "" };
}
