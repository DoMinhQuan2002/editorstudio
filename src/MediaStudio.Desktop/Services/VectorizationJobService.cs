using System.IO;

namespace MediaStudio.Desktop.Services;

public sealed class VectorizationJobService(MediaStudioApiClient apiClient)
{
    private static readonly TimeSpan JobWaitLimit = TimeSpan.FromMinutes(15);
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(400);

    public Task<ImportedAsset> ImportSourceAsync(string sourcePath, CancellationToken cancellationToken = default) =>
        apiClient.ImportImageAsync(sourcePath, cancellationToken);

    public async Task<VectorizationRunResult> RunAsync(
        string assetId,
        string vectorMethod,
        string qualityMode,
        string textMode,
        Action<BackendJob>? progressChanged = null,
        CancellationToken cancellationToken = default,
        int colorCount = 16,
        int detail = 50,
        bool removeBackground = true,
        string outputMode = "cutout")
    {
        if (vectorMethod is not ("smart_reconstruction" or "contour_preserving"))
        {
            throw new ArgumentOutOfRangeException(nameof(vectorMethod), "Phương pháp vector hóa không hợp lệ.");
        }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(JobWaitLimit);
        BackendJob job;
        try
        {
            job = await apiClient.StartVectorizeAsync(new VectorizeRequest
            {
                AssetId = assetId,
                Engine = "auto",
                Mode = qualityMode,
                ColorCount = Math.Clamp(colorCount, 2, 24),
                Detail = Math.Clamp(detail, 0, 100),
                SmoothPaths = true,
                TransparentBackground = removeBackground,
                OutputMode = outputMode == "vector" ? "vector" : "cutout",
                TextMode = textMode,
                VectorMethod = vectorMethod
            }, timeout.Token);

            progressChanged?.Invoke(job);
            while (job.State is not ("succeeded" or "failed"))
            {
                await Task.Delay(PollInterval, timeout.Token);
                job = await apiClient.GetJobAsync(job.JobId, timeout.Token);
                progressChanged?.Invoke(job);
            }
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new TimeoutException(
                "Đã hết thời gian chờ kết quả. Backend có thể vẫn đang xử lý; thao tác này không hủy job.");
        }

        if (job.State != "succeeded")
        {
            throw new BackendJobException(job.ErrorCode, job.Error ?? "Engine không thể xử lý ảnh.");
        }

        if (!string.Equals(job.AssetId, assetId, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Job trả về asset khác với ảnh nguồn được gửi.");
        }

        var svgBytes = await apiClient.DownloadResultAsync(job.JobId, timeout.Token);
        if (svgBytes.Length == 0)
        {
            throw new InvalidDataException("Backend trả về SVG rỗng.");
        }

        return new VectorizationRunResult(vectorMethod, job, svgBytes);
    }
}

public sealed record VectorizationRunResult(string VectorMethod, BackendJob Job, byte[] SvgBytes);

public sealed class BackendJobException(string? errorCode, string message) : InvalidOperationException(message)
{
    public string? ErrorCode { get; } = errorCode;
}
