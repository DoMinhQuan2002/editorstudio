using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

/// <summary>Fashion Studio: try-on, scene change, recolor and new views with Qwen-Image-Edit.</summary>
public sealed class FashionStudioViewModel : ObservableObject
{
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(800);
    private readonly MediaStudioApiClient? _api;
    private readonly IImagePicker _picker;
    private readonly string _outputFolder;

    private FashionTaskOption _selectedTask;
    private string? _personPath, _garmentPath;
    private BitmapImage? _personImage, _garmentImage;
    private FashionPresetOption? _selectedScene, _selectedView;
    private string _sceneText = "", _color = "", _extraPrompt = "";
    private string _statusState = "checking", _statusMessage = "Đang kiểm tra model…";
    private bool _isBusy;
    private int _progress;
    private bool _isIndeterminate;
    private string _stage = "";
    private string _error = "";
    private FashionResultItem? _selectedResult;

    public FashionStudioViewModel(MediaStudioApiClient? api, IImagePicker picker)
    {
        _api = api;
        _picker = picker;
        _outputFolder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyPictures), "Media Studio", "Fashion Studio");

        Tasks =
        [
            new("try_on", "Thử đồ ảo", "Mặc trang phục từ ảnh sản phẩm lên người mẫu", "\uE8EC", true),
            new("scene", "Đổi bối cảnh", "Đưa người mẫu vào phố, studio, biển… giữ nguyên đồ", "\uE909", true),
            new("recolor", "Đổi màu trang phục", "Tạo biến thể màu cho cùng một bộ đồ", "\uE790", true),
            new("new_view", "Góc nhìn mới", "Toàn thân, nghiêng, sau lưng, cận chi tiết", "\uE7C5", true),
        ];
        _selectedTask = Tasks[0];
        _selectedTask.IsSelected = true;

        ScenePresets =
        [
            new("studio", "Studio"), new("street", "Đường phố"), new("cafe", "Quán cà phê"),
            new("beach", "Bãi biển"), new("autumn_park", "Công viên mùa thu"), new("runway", "Sàn diễn"),
        ];
        ViewPresets =
        [
            new("full_body", "Toàn thân"), new("side", "Nghiêng 3/4"), new("back", "Sau lưng"), new("close_up", "Cận chi tiết"),
        ];
        _selectedScene = ScenePresets[0];
        _selectedView = ViewPresets[0];

        SelectTaskCommand = new RelayCommand(value => { if (value is FashionTaskOption task) SelectedTask = task; });
        PickPersonCommand = new RelayCommand(_ => PickImage(isPerson: true), _ => !IsBusy);
        PickGarmentCommand = new RelayCommand(_ => PickImage(isPerson: false), _ => !IsBusy);
        ClearGarmentCommand = new RelayCommand(_ => SetGarment(null), _ => !IsBusy);
        SelectSceneCommand = new RelayCommand(value => { if (value is FashionPresetOption p) SelectedScene = p; });
        SelectViewCommand = new RelayCommand(value => { if (value is FashionPresetOption p) SelectedView = p; });
        GenerateCommand = new AsyncRelayCommand(GenerateAsync, _ => CanGenerate);
        DownloadModelCommand = new AsyncRelayCommand(DownloadModelAsync, _ => !IsBusy && StatusState == "model_missing");
        RefreshStatusCommand = new AsyncRelayCommand(RefreshStatusAsync, _ => !IsBusy);
        OpenFolderCommand = new RelayCommand(_ => OpenFolder());
        UseResultAsPersonCommand = new RelayCommand(_ => { if (SelectedResult is { } r) SetPerson(r.FilePath); }, _ => SelectedResult is not null && !IsBusy);
        SelectResultCommand = new RelayCommand(value => { if (value is FashionResultItem r) SelectedResult = r; });

        _ = RefreshStatusAsync();
    }

    // ------------------------------------------------------------------ options
    public ObservableCollection<FashionTaskOption> Tasks { get; }
    public ObservableCollection<FashionPresetOption> ScenePresets { get; }
    public ObservableCollection<FashionPresetOption> ViewPresets { get; }
    public ObservableCollection<FashionResultItem> Results { get; } = [];

    public FashionTaskOption SelectedTask
    {
        get => _selectedTask;
        set
        {
            if (value == _selectedTask) return;
            _selectedTask.IsSelected = false;
            _selectedTask = value;
            value.IsSelected = true;
            OnPropertyChanged();
            OnPropertyChanged(nameof(IsTryOn)); OnPropertyChanged(nameof(IsScene));
            OnPropertyChanged(nameof(IsRecolor)); OnPropertyChanged(nameof(IsNewView));
            Error = "";
            Refresh();
        }
    }
    public bool IsTryOn => SelectedTask.Id == "try_on";
    public bool IsScene => SelectedTask.Id == "scene";
    public bool IsRecolor => SelectedTask.Id == "recolor";
    public bool IsNewView => SelectedTask.Id == "new_view";

    public FashionPresetOption? SelectedScene
    {
        get => _selectedScene;
        set { if (_selectedScene is not null) _selectedScene.IsSelected = false; _selectedScene = value; if (value is not null) value.IsSelected = true; OnPropertyChanged(); }
    }
    public FashionPresetOption? SelectedView
    {
        get => _selectedView;
        set { if (_selectedView is not null) _selectedView.IsSelected = false; _selectedView = value; if (value is not null) value.IsSelected = true; OnPropertyChanged(); }
    }

    // ------------------------------------------------------------------ inputs
    public BitmapImage? PersonImage { get => _personImage; private set { SetProperty(ref _personImage, value); OnPropertyChanged(nameof(HasPerson)); } }
    public BitmapImage? GarmentImage { get => _garmentImage; private set { SetProperty(ref _garmentImage, value); OnPropertyChanged(nameof(HasGarment)); } }
    public bool HasPerson => _personPath is not null;
    public bool HasGarment => _garmentPath is not null;
    public string PersonFileName => _personPath is null ? "" : Path.GetFileName(_personPath);
    public string GarmentFileName => _garmentPath is null ? "" : Path.GetFileName(_garmentPath);
    public string SceneText { get => _sceneText; set { SetProperty(ref _sceneText, value); Refresh(); } }
    public string Color { get => _color; set { SetProperty(ref _color, value); Refresh(); } }
    public string ExtraPrompt { get => _extraPrompt; set => SetProperty(ref _extraPrompt, value); }

    // ------------------------------------------------------------------ status / progress
    public string StatusState { get => _statusState; private set { SetProperty(ref _statusState, value); OnPropertyChanged(nameof(IsReady)); OnPropertyChanged(nameof(ShowSetupBanner)); OnPropertyChanged(nameof(CanDownloadModel)); Refresh(); } }
    public string StatusMessage { get => _statusMessage; private set => SetProperty(ref _statusMessage, value); }
    public bool IsReady => StatusState == "ready";
    public bool ShowSetupBanner => !IsReady;
    public bool CanDownloadModel => StatusState == "model_missing";
    public bool IsBusy { get => _isBusy; private set { SetProperty(ref _isBusy, value); Refresh(); } }
    public int Progress { get => _progress; private set => SetProperty(ref _progress, value); }
    public bool IsIndeterminate { get => _isIndeterminate; private set => SetProperty(ref _isIndeterminate, value); }
    public string Stage { get => _stage; private set => SetProperty(ref _stage, value); }
    public string Error { get => _error; private set { SetProperty(ref _error, value); OnPropertyChanged(nameof(HasError)); } }
    public bool HasError => !string.IsNullOrEmpty(Error);

    public FashionResultItem? SelectedResult
    {
        get => _selectedResult;
        set
        {
            if (_selectedResult is not null) _selectedResult.IsSelected = false;
            SetProperty(ref _selectedResult, value);
            if (value is not null) value.IsSelected = true;
            OnPropertyChanged(nameof(HasResult));
            UseResultAsPersonCommand?.NotifyCanExecuteChanged();
        }
    }
    public bool HasResult => SelectedResult is not null;

    public string GenerateHint => !IsReady ? "Model chưa sẵn sàng"
        : !HasPerson ? "Thêm ảnh người mẫu"
        : IsTryOn && !HasGarment ? "Thêm ảnh trang phục"
        : IsRecolor && string.IsNullOrWhiteSpace(Color) ? "Nhập màu mới"
        : IsScene && SelectedScene is null && string.IsNullOrWhiteSpace(SceneText) ? "Chọn bối cảnh"
        : "Mỗi ảnh mất khoảng 1–5 phút tùy GPU";

    private bool CanGenerate => !IsBusy && IsReady && HasPerson
        && (!IsTryOn || HasGarment)
        && (!IsRecolor || !string.IsNullOrWhiteSpace(Color));

    // ------------------------------------------------------------------ commands
    public RelayCommand SelectTaskCommand { get; }
    public RelayCommand PickPersonCommand { get; }
    public RelayCommand PickGarmentCommand { get; }
    public RelayCommand ClearGarmentCommand { get; }
    public RelayCommand SelectSceneCommand { get; }
    public RelayCommand SelectViewCommand { get; }
    public AsyncRelayCommand GenerateCommand { get; }
    public AsyncRelayCommand DownloadModelCommand { get; }
    public AsyncRelayCommand RefreshStatusCommand { get; }
    public RelayCommand OpenFolderCommand { get; }
    public RelayCommand UseResultAsPersonCommand { get; }
    public RelayCommand SelectResultCommand { get; }

    private void PickImage(bool isPerson)
    {
        var path = _picker.PickImage();
        if (path is null) return;
        if (isPerson) SetPerson(path); else SetGarment(path);
    }

    private void SetPerson(string? path)
    {
        _personPath = path;
        PersonImage = path is null ? null : Load(path);
        OnPropertyChanged(nameof(PersonFileName));
        Refresh();
    }

    private void SetGarment(string? path)
    {
        _garmentPath = path;
        GarmentImage = path is null ? null : Load(path);
        OnPropertyChanged(nameof(GarmentFileName));
        Refresh();
    }

    private async Task RefreshStatusAsync()
    {
        if (_api is null)
        {
            StatusState = "offline";
            StatusMessage = "Python backend chưa kết nối nên chưa dùng được Fashion Studio.";
            return;
        }
        try
        {
            var status = await _api.GetFashionStatusAsync();
            StatusMessage = status.Message;
            StatusState = status.State;
        }
        catch (Exception error)
        {
            StatusState = "offline";
            StatusMessage = "Không kiểm tra được model: " + error.Message;
        }
    }

    private async Task DownloadModelAsync()
    {
        if (_api is null) return;
        IsBusy = true; Error = "";
        try
        {
            var job = await _api.StartFashionDownloadAsync();
            job = await PollAsync(job);
            if (job.State != "succeeded") Error = job.Error ?? "Tải model thất bại.";
        }
        catch (Exception error) { Error = error.Message; }
        finally { IsBusy = false; Stage = ""; await RefreshStatusAsync(); }
    }

    private async Task GenerateAsync()
    {
        if (_api is null || _personPath is null) return;
        IsBusy = true; Error = ""; Progress = 0;
        try
        {
            Stage = "Đang gửi ảnh…"; IsIndeterminate = true;
            var person = await _api.ImportImageAsync(_personPath);
            string? garmentId = null;
            if (IsTryOn && _garmentPath is not null) garmentId = (await _api.ImportImageAsync(_garmentPath)).AssetId;

            var job = await _api.StartFashionJobAsync(new FashionJobRequestDto
            {
                Task = SelectedTask.Id,
                PersonAssetId = person.AssetId,
                GarmentAssetId = garmentId,
                ScenePreset = IsScene && string.IsNullOrWhiteSpace(SceneText) ? SelectedScene?.Id : null,
                SceneText = IsScene && !string.IsNullOrWhiteSpace(SceneText) ? SceneText.Trim() : null,
                Color = IsRecolor ? Color.Trim() : null,
                ViewPreset = IsNewView ? SelectedView?.Id : null,
                ExtraPrompt = string.IsNullOrWhiteSpace(ExtraPrompt) ? null : ExtraPrompt.Trim(),
            });
            job = await PollAsync(job);
            if (job.State != "succeeded")
            {
                Error = job.Error ?? "Không tạo được ảnh.";
                return;
            }

            var bytes = await _api.DownloadResultAsync(job.JobId);
            Directory.CreateDirectory(_outputFolder);
            var file = Path.Combine(_outputFolder, $"{DateTime.Now:yyyyMMdd-HHmmss}-{SelectedTask.Id}.png");
            await File.WriteAllBytesAsync(file, bytes);
            var seconds = job.ResultProcessingTimeMs is double ms ? $" · {ms / 1000.0:0} giây" : "";
            var item = new FashionResultItem(file, Load(file), $"{SelectedTask.Title}{seconds}");
            Results.Insert(0, item);
            SelectedResult = item;
            Stage = "Đã tạo ảnh xong";
        }
        catch (Exception error) { Error = error.Message; }
        finally { IsBusy = false; IsIndeterminate = false; }
    }

    private async Task<BackendJob> PollAsync(BackendJob job)
    {
        Apply(job);
        while (job.State is not ("succeeded" or "failed"))
        {
            await Task.Delay(PollInterval);
            job = await _api!.GetJobAsync(job.JobId);
            Apply(job);
        }
        return job;
    }

    private void Apply(BackendJob job)
    {
        Stage = job.Stage;
        Progress = job.Progress;
        IsIndeterminate = job.IsIndeterminate;
    }

    private void OpenFolder()
    {
        Directory.CreateDirectory(_outputFolder);
        var target = SelectedResult?.FilePath;
        Process.Start(new ProcessStartInfo("explorer.exe", target is null ? $"\"{_outputFolder}\"" : $"/select,\"{target}\"") { UseShellExecute = true });
    }

    private void Refresh()
    {
        OnPropertyChanged(nameof(GenerateHint));
        GenerateCommand?.NotifyCanExecuteChanged();
        DownloadModelCommand?.NotifyCanExecuteChanged();
        RefreshStatusCommand?.NotifyCanExecuteChanged();
        PickPersonCommand?.NotifyCanExecuteChanged();
        PickGarmentCommand?.NotifyCanExecuteChanged();
        ClearGarmentCommand?.NotifyCanExecuteChanged();
        UseResultAsPersonCommand?.NotifyCanExecuteChanged();
    }

    private static BitmapImage Load(string path)
    {
        var image = new BitmapImage();
        image.BeginInit();
        image.CacheOption = BitmapCacheOption.OnLoad;
        image.CreateOptions = BitmapCreateOptions.IgnoreImageCache;
        image.UriSource = new Uri(path);
        image.EndInit();
        image.Freeze();
        return image;
    }
}

public sealed class FashionTaskOption(string id, string title, string description, string icon, bool enabled) : ObservableObject
{
    private bool _isSelected;
    public string Id { get; } = id;
    public string Title { get; } = title;
    public string Description { get; } = description;
    public string Icon { get; } = icon;
    public bool IsEnabled { get; } = enabled;
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }
}

public sealed class FashionPresetOption(string id, string label) : ObservableObject
{
    private bool _isSelected;
    public string Id { get; } = id;
    public string Label { get; } = label;
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }
}

public sealed class FashionResultItem(string filePath, BitmapImage image, string caption) : ObservableObject
{
    private bool _isSelected;
    public string FilePath { get; } = filePath;
    public BitmapImage Image { get; } = image;
    public string Caption { get; } = caption;
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }
}
