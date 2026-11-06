namespace MediaStudio.Desktop.Services;

/// <summary>Asked before any export (video or image). Set at startup to the account check;
/// returns false when the export must not start (e.g. premium template without a plan).</summary>
public static class ExportGate
{
    public static Func<string, Task<bool>>? Check { get; set; }

    public static async Task<bool> AllowAsync(string templateId) => Check is null || await Check(templateId);
}
