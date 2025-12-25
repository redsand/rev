using System;

namespace RevExtension.Utilities
{
    internal static class RevIdeHelpers
    {
        public static string BuildWebSocketUrl(string apiUrl)
        {
            if (string.IsNullOrWhiteSpace(apiUrl))
            {
                return null;
            }

            if (!Uri.TryCreate(apiUrl, UriKind.Absolute, out var uri))
            {
                return null;
            }

            var scheme = uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase) ? "wss" : "ws";
            var builder = new UriBuilder(uri)
            {
                Scheme = scheme,
                Path = "/ws",
                Query = string.Empty,
                Fragment = string.Empty
            };
            return builder.Uri.ToString();
        }

        public static string GetPythonPathFromEnvironment()
        {
            var pythonPath = Environment.GetEnvironmentVariable("REV_IDE_PYTHON_PATH");
            if (!string.IsNullOrWhiteSpace(pythonPath))
            {
                return pythonPath;
            }

            pythonPath = Environment.GetEnvironmentVariable("REV_PYTHON_PATH");
            if (!string.IsNullOrWhiteSpace(pythonPath))
            {
                return pythonPath;
            }

            pythonPath = Environment.GetEnvironmentVariable("REV_PYTHON");
            if (!string.IsNullOrWhiteSpace(pythonPath))
            {
                return pythonPath;
            }

            return "python";
        }

        public static int ComputeReconnectDelay(int attempt)
        {
            if (attempt < 0)
            {
                attempt = 0;
            }

            var delay = 500 * Math.Pow(2, attempt);
            if (delay > 5000)
            {
                delay = 5000;
            }

            return (int)delay;
        }
    }
}
