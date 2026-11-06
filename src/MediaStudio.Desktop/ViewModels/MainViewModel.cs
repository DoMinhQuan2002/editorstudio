using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.Infrastructure;
using System.Windows;

namespace MediaStudio.Desktop.ViewModels;

public enum MainWorkspaceKind
{
    ImageTools,
    VideoEditor,
    FashionStudio
}

public sealed class MainViewModel : ObservableObject
{
    private MainWorkspaceKind _selectedWorkspace = MainWorkspaceKind.ImageTools;

    public MainViewModel(
        IImagePicker imagePicker,
        MediaStudioApiClient? apiClient,
        string engineStatus,
        string engineDescription,
        BackendHealth? backendHealth = null,
        AccountService? account = null)
    {
        Account = new AccountViewModel(account ?? new AccountService(AccountSettings.Load()));
        // Premium templates: everything up to step 6 works; exporting asks the account server first.
        ExportGate.Check = Account.CheckExportAsync;
        ImageTools = new ImageToolsViewModel(imagePicker, apiClient, backendHealth);
        FashionStudio = new FashionStudioViewModel(apiClient, imagePicker);
        VideoCreator = new VideoCreatorGalleryViewModel(
            apiClient is null ? null : new TemplateCatalogService(apiClient),
            apiClient is null ? null : new MediaSelectionService(apiClient),
            processingService: apiClient is null ? null : new TemplateProcessingService(apiClient),
            draftPreviewService: apiClient is null ? null : new VideoCreatorDraftPreviewService(apiClient),
            exportService: apiClient is null ? null : new MediaStudioVideoCreatorExportService(apiClient),
            storyService: apiClient is null ? null : new StoryTemplateService(apiClient));
        SelectWorkspaceCommand = new RelayCommand(parameter =>
        {
            if (parameter is not MainWorkspaceKind workspace) return;
            // Clicking Video Editor while a template is open asks whether to keep editing or start over.
            if (workspace == MainWorkspaceKind.VideoEditor && VideoCreator.IsDetailsVisible)
            {
                IsLeaveTemplatePromptOpen = true;
                return;
            }
            SelectedWorkspace = workspace;
        });
        ContinueTemplateEditingCommand = new RelayCommand(_ =>
        {
            IsLeaveTemplatePromptOpen = false;
            SelectedWorkspace = MainWorkspaceKind.VideoEditor;
        });
        DiscardTemplateEditingCommand = new RelayCommand(_ =>
        {
            IsLeaveTemplatePromptOpen = false;
            VideoCreator.ReturnToGallery();
            SelectedWorkspace = MainWorkspaceKind.VideoEditor;
        });
        EngineStatus = engineStatus;
        EngineDescription = engineDescription;
        EngineConnected = engineStatus.Contains("đã kết nối", StringComparison.OrdinalIgnoreCase);
    }

    public AccountViewModel Account { get; }
    public ImageToolsViewModel ImageTools { get; }
    public FashionStudioViewModel FashionStudio { get; }
    public VideoCreatorGalleryViewModel VideoCreator { get; }
    public string EngineStatus { get; }
    public string EngineDescription { get; }
    public bool EngineConnected { get; }
    public RelayCommand SelectWorkspaceCommand { get; }
    public RelayCommand ContinueTemplateEditingCommand { get; }
    public RelayCommand DiscardTemplateEditingCommand { get; }
    private bool _isLeaveTemplatePromptOpen;
    public bool IsLeaveTemplatePromptOpen { get => _isLeaveTemplatePromptOpen; private set => SetProperty(ref _isLeaveTemplatePromptOpen, value); }

    public MainWorkspaceKind SelectedWorkspace
    {
        get => _selectedWorkspace;
        private set
        {
            if (!SetProperty(ref _selectedWorkspace, value)) return;
            OnPropertyChanged(nameof(IsImageToolsWorkspace));
            OnPropertyChanged(nameof(IsVideoEditorWorkspace));
            OnPropertyChanged(nameof(IsFashionStudioWorkspace));
            OnPropertyChanged(nameof(IsSidebarExpanded));
            OnPropertyChanged(nameof(SidebarWidth));
            OnPropertyChanged(nameof(WorkspaceHeaderHeight));
            OnPropertyChanged(nameof(WorkspaceTitle));
            OnPropertyChanged(nameof(WindowTitle));
        }
    }

    public bool IsImageToolsWorkspace => SelectedWorkspace == MainWorkspaceKind.ImageTools;
    public bool IsVideoEditorWorkspace => SelectedWorkspace == MainWorkspaceKind.VideoEditor;
    public bool IsFashionStudioWorkspace => SelectedWorkspace == MainWorkspaceKind.FashionStudio;
    public bool IsSidebarExpanded => true;
    public GridLength SidebarWidth => new(272);
    public GridLength WorkspaceHeaderHeight => new(IsImageToolsWorkspace ? 64 : 60);
    public string WorkspaceTitle => SelectedWorkspace switch
    {
        MainWorkspaceKind.VideoEditor => "Video Editor",
        MainWorkspaceKind.FashionStudio => "Fashion Studio",
        _ => "Công cụ hình ảnh",
    };
    public string WindowTitle => "Media Studio — " + SelectedWorkspace switch
    {
        MainWorkspaceKind.VideoEditor => "Video Editor",
        MainWorkspaceKind.FashionStudio => "Fashion Studio",
        _ => "Image Tools",
    };
}
