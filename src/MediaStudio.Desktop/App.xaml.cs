using System.IO;
using System.Windows;
using System.Windows.Threading;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop;

public partial class App : Application
{
    private BackendProcessHost? _backendHost;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
        LogStartup("Application startup entered.");
        _backendHost = new BackendProcessHost();
        string engineStatus;
        string engineDescription;

        try
        {
            LogStartup("Starting Python backend.");
            await _backendHost.StartAsync();
            engineStatus = "Python backend đã kết nối";
            engineDescription = _backendHost.Health?.Device ?? "AI engine sẵn sàng";
            LogStartup($"Backend connected. Device: {engineDescription}");
        }
        catch (Exception error)
        {
            LogStartup($"Backend startup failed: {error}");
            await _backendHost.StopAsync();
            engineStatus = "Python backend chưa kết nối";
            engineDescription = error.Message;
        }

        try
        {
            LogStartup("Creating main window.");
            var mainViewModel = new MainViewModel(new WpfImagePicker(), _backendHost.ApiClient,
                engineStatus, engineDescription, _backendHost.Health,
                new AccountService(AccountSettings.Load()));
            MainWindow = new MainWindow(mainViewModel);
            MainWindow.Show();
            LogStartup("Restoring account session.");
            await mainViewModel.Account.StartAsync();
            ShutdownMode = ShutdownMode.OnMainWindowClose;
            LogStartup("Main window shown.");
        }
        catch (Exception error)
        {
            LogStartup($"Main window startup failed: {error}");
            await _backendHost.StopAsync();
            MessageBox.Show(
                $"Không thể mở giao diện Media Studio. Chi tiết đã được ghi vào app-startup.log.\n\n{error.Message}",
                "Media Studio",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown();
        }
    }

    protected override async void OnExit(ExitEventArgs e)
    {
        LogStartup("Application exiting.");
        if (_backendHost is not null)
        {
            await _backendHost.DisposeAsync();
        }
        base.OnExit(e);
    }

    private static void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        LogStartup($"Unhandled dispatcher exception: {e.Exception}");
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        LogStartup($"Unhandled application exception (terminating={e.IsTerminating}): {e.ExceptionObject}");
    }

    private static void LogStartup(string message)
    {
        try
        {
            var directory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MediaStudio");
            Directory.CreateDirectory(directory);
            File.AppendAllText(
                Path.Combine(directory, "app-startup.log"),
                $"[{DateTimeOffset.Now:O}] {message}{Environment.NewLine}");
        }
        catch
        {
            // Startup diagnostics must not prevent the application from opening.
        }
    }
}
