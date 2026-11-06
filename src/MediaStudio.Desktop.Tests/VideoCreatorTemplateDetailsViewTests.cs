using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows.Controls;
using MediaStudio.Desktop.Views;

namespace MediaStudio.Desktop.Tests;

public sealed class VideoCreatorTemplateDetailsViewTests
{
    [Fact]
    public void ConstructorLoadsTheDetailsXamlContent()
    {
        Grid? root = null;
        ExceptionDispatchInfo? captured = null;
        var thread = new Thread(() =>
        {
            try
            {
                var app = new App();
                app.InitializeComponent();
                var view = new VideoCreatorTemplateDetailsView();
                root = Assert.IsType<Grid>(view.Content);
            }
            catch (Exception error)
            {
                captured = ExceptionDispatchInfo.Capture(error);
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        captured?.Throw();
        Assert.NotNull(root);
    }
}
