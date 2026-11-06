using System.Windows;
using System.Windows.Controls;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

public partial class VideoCreatorGalleryView : UserControl
{
    public VideoCreatorGalleryView() => InitializeComponent();

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (DataContext is VideoCreatorGalleryViewModel viewModel)
            await viewModel.LoadCatalogAsync();
    }
}
