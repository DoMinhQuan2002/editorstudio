using System.Windows;
using System.ComponentModel;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop;

public partial class MainWindow : Window
{
    private readonly VideoCreatorGalleryViewModel _videoCreator;

    public MainWindow(MainViewModel viewModel)
    {
        VideoCreatorRuntimeDiagnostics.EnableBindingDiagnostics();
        InitializeComponent();

        var workArea = SystemParameters.WorkArea;
        MinWidth = Math.Min(1280, workArea.Width * 0.9);
        MinHeight = Math.Min(720, workArea.Height * 0.85);
        Width = Math.Min(1440, workArea.Width * 0.96);
        Height = Math.Min(900, workArea.Height * 0.92);

        _videoCreator = viewModel.VideoCreator;
        DataContext = viewModel;
        VideoCreatorGalleryHost.DataContext = _videoCreator;
        _videoCreator.PropertyChanged += OnVideoCreatorPropertyChanged;
        Closed += (_, _) => _videoCreator.PropertyChanged -= OnVideoCreatorPropertyChanged;
        UpdateVideoCreatorPage();
    }

    private void OnAccountButtonClick(object sender, RoutedEventArgs e)
    {
        if (sender is System.Windows.Controls.Button { ContextMenu: { } menu } button)
        {
            menu.PlacementTarget = button;
            menu.Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom;
            menu.IsOpen = true;
        }
    }

    private async void OnShowPlansClick(object sender, RoutedEventArgs e) =>
        await ((MainViewModel)DataContext).Account.OpenPlanPickerAsync("Gói Pro mở khóa xuất video và ảnh từ tất cả các mẫu, kể cả mẫu trả phí.");

    private void OnVideoCreatorPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is not (nameof(VideoCreatorGalleryViewModel.CurrentDetails)
            or nameof(VideoCreatorGalleryViewModel.CurrentSelection)
            or nameof(VideoCreatorGalleryViewModel.CurrentProcessing)
            or nameof(VideoCreatorGalleryViewModel.CurrentDraftPreview)
            or nameof(VideoCreatorGalleryViewModel.CurrentExport)
            or nameof(VideoCreatorGalleryViewModel.CurrentStoryResult))) return;

        if (Dispatcher.CheckAccess())
            UpdateVideoCreatorPage();
        else
            Dispatcher.BeginInvoke(UpdateVideoCreatorPage);
    }

    private void UpdateVideoCreatorPage()
    {
        var details = _videoCreator.CurrentDetails;
        var selection = _videoCreator.CurrentSelection;
        var processing = _videoCreator.CurrentProcessing;
        var draftPreview = _videoCreator.CurrentDraftPreview;
        var export = _videoCreator.CurrentExport;
        var story = _videoCreator.CurrentStoryResult;
        StoryResultHost.DataContext = story;
        StoryResultHost.Visibility = story is null || selection is not null ? Visibility.Collapsed : Visibility.Visible;
        MediaSelectionHost.DataContext = selection;
        MediaSelectionHost.Visibility = selection is null ? Visibility.Collapsed : Visibility.Visible;
        VideoCreatorProcessingHost.DataContext = processing;
        VideoCreatorProcessingHost.Visibility = processing is null || selection is not null || draftPreview is not null
            ? Visibility.Collapsed : Visibility.Visible;
        VideoCreatorDraftPreviewHost.DataContext = draftPreview;
        VideoCreatorDraftPreviewHost.Visibility = draftPreview is null || selection is not null || export is not null
            ? Visibility.Collapsed : Visibility.Visible;
        VideoCreatorExportHost.DataContext = export;
        VideoCreatorExportHost.Visibility = export is null || selection is not null
            ? Visibility.Collapsed : Visibility.Visible;
        VideoCreatorDetailsHost.DataContext = details;
        VideoCreatorGalleryHost.Visibility = details is null && selection is null && processing is null && draftPreview is null && export is null && story is null
            ? Visibility.Visible : Visibility.Collapsed;
        VideoCreatorDetailsHost.Visibility = details is null || selection is not null || processing is not null || draftPreview is not null || export is not null || story is not null
            ? Visibility.Collapsed : Visibility.Visible;
        VideoCreatorRuntimeDiagnostics.LogNavigation(
            $"templateId={details?.TemplateId ?? "<gallery>"}; " +
            $"view={VideoCreatorDetailsHost.GetType().FullName}; " +
            $"dataContext={VideoCreatorDetailsHost.DataContext?.GetType().FullName ?? "<null>"}; " +
            $"galleryVisibility={VideoCreatorGalleryHost.Visibility}; " +
            $"detailsVisibility={VideoCreatorDetailsHost.Visibility}; " +
            $"processingVisibility={VideoCreatorProcessingHost.Visibility}; " +
            $"draftPreviewVisibility={VideoCreatorDraftPreviewHost.Visibility}");
    }
}
