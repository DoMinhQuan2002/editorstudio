using System.Windows.Input;

namespace MediaStudio.Desktop.Infrastructure;

public sealed class AsyncRelayCommand(Func<Task> execute, Predicate<object?>? canExecute = null) : ICommand
{
    private readonly Func<Task> _execute = execute;
    private readonly Predicate<object?>? _canExecute = canExecute;
    private bool _isRunning;

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter) => !_isRunning && (_canExecute?.Invoke(parameter) ?? true);

    public async void Execute(object? parameter) => await ExecuteAsync(parameter);

    public async Task ExecuteAsync(object? parameter = null)
    {
        if (!CanExecute(parameter)) return;
        _isRunning = true;
        NotifyCanExecuteChanged();
        try
        {
            await _execute();
        }
        finally
        {
            _isRunning = false;
            NotifyCanExecuteChanged();
        }
    }

    public void NotifyCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
