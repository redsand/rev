using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using EnvDTE;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Shell.Interop;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using RevExtension.Utilities;

namespace RevExtension.Commands
{
    /// <summary>
    /// Base class for Rev commands
    /// </summary>
    public abstract class BaseRevCommand
    {
        protected readonly AsyncPackage package;
        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(300) };
        private static readonly Guid OutputPaneGuid = new Guid("b7c3f8a1-0e8f-4c9d-8b9f-8732c71f5bda");
        private static IVsOutputWindowPane outputPane;

        private static readonly object logSocketLock = new object();
        private static readonly object apiServerLock = new object();
        private static ClientWebSocket logSocket;
        private static CancellationTokenSource logSocketCts;
        private static Task logSocketTask;
        private static string logSocketUrl;
        private static bool logSocketConnecting;
        private static bool logSocketManualClose;
        private static int logSocketReconnectAttempts;
        private static Task logSocketReconnectTask;
        private static Process apiServerProcess;
        private static bool apiServerStartedByExtension;

        protected BaseRevCommand(AsyncPackage package)
        {
            this.package = package ?? throw new ArgumentNullException(nameof(package));
        }

        /// <summary>
        /// Gets the API URL from settings
        /// </summary>
        protected string GetApiUrl()
        {
            var envUrl = Environment.GetEnvironmentVariable("REV_IDE_API_URL");
            if (!string.IsNullOrWhiteSpace(envUrl))
            {
                return envUrl;
            }

            envUrl = Environment.GetEnvironmentVariable("REV_API_URL");
            if (!string.IsNullOrWhiteSpace(envUrl))
            {
                return envUrl;
            }

            return "http://127.0.0.1:8765";
        }

        /// <summary>
        /// Get the active document path
        /// </summary>
        protected async Task<string> GetActiveDocumentPathAsync()
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();

            var dte = await package.GetServiceAsync(typeof(DTE)) as DTE;
            if (dte?.ActiveDocument == null)
            {
                throw new InvalidOperationException("No active document");
            }

            return dte.ActiveDocument.FullName;
        }

        /// <summary>
        /// Get selected text range
        /// </summary>
        protected async Task<(int startLine, int endLine)?> GetSelectedRangeAsync()
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();

            var dte = await package.GetServiceAsync(typeof(DTE)) as DTE;
            if (dte?.ActiveDocument == null)
            {
                return null;
            }

            var textSelection = dte.ActiveDocument.Selection as TextSelection;
            if (textSelection == null || textSelection.IsEmpty)
            {
                return null;
            }

            return (textSelection.TopPoint.Line, textSelection.BottomPoint.Line);
        }

        /// <summary>
        /// Make API request to Rev
        /// </summary>
        protected async Task<JObject> MakeApiRequestAsync(string endpoint, object data)
        {
            try
            {
                await EnsureApiServerRunningAsync();
                await EnsureLogStreamAsync();
                var apiUrl = GetApiUrl();
                var json = JsonConvert.SerializeObject(data);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                var response = await httpClient.PostAsync($"{apiUrl}{endpoint}", content);
                response.EnsureSuccessStatusCode();

                var responseContent = await response.Content.ReadAsStringAsync();
                return JObject.Parse(responseContent);
            }
            catch (HttpRequestException ex)
            {
                throw new Exception($"Rev API error: {ex.Message}. Ensure the Rev API server is running.", ex);
            }
        }

        public static void RequestStopApiServer()
        {
            _ = ThreadHelper.JoinableTaskFactory.RunAsync(async () => await StopApiServerAsync());
        }

        /// <summary>
        /// Show message to user
        /// </summary>
        protected async Task ShowMessageAsync(string message, bool isError = false)
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();

            if (isError)
            {
                VsShellUtilities.ShowMessageBox(
                    package,
                    message,
                    "Rev Error",
                    OLEMSGICON.OLEMSGICON_CRITICAL,
                    OLEMSGBUTTON.OLEMSGBUTTON_OK,
                    OLEMSGDEFBUTTON.OLEMSGDEFBUTTON_FIRST);
            }
            else
            {
                VsShellUtilities.ShowMessageBox(
                    package,
                    message,
                    "Rev",
                    OLEMSGICON.OLEMSGICON_INFO,
                    OLEMSGBUTTON.OLEMSGBUTTON_OK,
                    OLEMSGDEFBUTTON.OLEMSGDEFBUTTON_FIRST);
            }
        }

        /// <summary>
        /// Log to output window
        /// </summary>
        protected void LogToOutput(string message)
        {
            _ = ThreadHelper.JoinableTaskFactory.RunAsync(async () =>
            {
                var pane = await EnsureOutputPaneAsync();
                if (pane == null)
                {
                    System.Diagnostics.Debug.WriteLine($"[Rev] {message}");
                    return;
                }
                pane.OutputStringThreadSafe($"[Rev] {message}{Environment.NewLine}");
            });
        }

        private async Task<IVsOutputWindowPane> EnsureOutputPaneAsync()
        {
            if (outputPane != null)
            {
                return outputPane;
            }

            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
            var outputWindow = await package.GetServiceAsync(typeof(SVsOutputWindow)) as IVsOutputWindow;
            if (outputWindow == null)
            {
                return null;
            }

            outputWindow.CreatePane(ref OutputPaneGuid, "Rev", 1, 1);
            outputWindow.GetPane(ref OutputPaneGuid, out outputPane);
            return outputPane;
        }

        private async Task EnsureApiServerRunningAsync()
        {
            if (IsApiServerProcessAlive())
            {
                return;
            }

            if (await IsApiServerResponsiveAsync())
            {
                return;
            }

            await StartApiServerAsync();
        }

        private async Task<bool> IsApiServerResponsiveAsync()
        {
            try
            {
                var apiUrl = GetApiUrl();
                var response = await httpClient.GetAsync($"{apiUrl}/api/v1/models/current");
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        private async Task StartApiServerAsync()
        {
            lock (apiServerLock)
            {
                if (IsApiServerProcessAlive())
                {
                    return;
                }
            }

            var pythonPath = RevIdeHelpers.GetPythonPathFromEnvironment();
            var workingDir = await GetWorkspaceDirectoryAsync();

            var startInfo = new ProcessStartInfo
            {
                FileName = pythonPath,
                Arguments = "-m rev.ide.api_server",
                WorkingDirectory = workingDir,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, args) =>
            {
                if (!string.IsNullOrWhiteSpace(args.Data))
                {
                    LogToOutput($"API: {args.Data}");
                }
            };
            process.ErrorDataReceived += (_, args) =>
            {
                if (!string.IsNullOrWhiteSpace(args.Data))
                {
                    LogToOutput($"API Error: {args.Data}");
                }
            };
            process.Exited += (_, __) => LogToOutput($"API server exited with code {process.ExitCode}");

            try
            {
                if (!process.Start())
                {
                    LogToOutput("API Error: Failed to start Rev API server.");
                    return;
                }

                process.BeginOutputReadLine();
                process.BeginErrorReadLine();

                lock (apiServerLock)
                {
                    apiServerProcess = process;
                    apiServerStartedByExtension = true;
                }

                LogToOutput("Rev API server started");
                await Task.Delay(500);
            }
            catch (Exception ex)
            {
                LogToOutput($"API Error: {ex.Message}");
                process.Dispose();
            }
        }

        private async Task<string> GetWorkspaceDirectoryAsync()
        {
            try
            {
                await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                var dte = await package.GetServiceAsync(typeof(DTE)) as DTE;
                var solutionPath = dte?.Solution?.FullName;
                if (!string.IsNullOrWhiteSpace(solutionPath))
                {
                    return Path.GetDirectoryName(solutionPath);
                }
            }
            catch
            {
                // Ignore and fall back to current directory
            }
            return Directory.GetCurrentDirectory();
        }

        private static bool IsApiServerProcessAlive()
        {
            lock (apiServerLock)
            {
                return apiServerProcess != null && !apiServerProcess.HasExited;
            }
        }

        private static async Task StopApiServerAsync()
        {
            Process process = null;
            bool shouldStop = false;

            lock (apiServerLock)
            {
                process = apiServerProcess;
                shouldStop = apiServerStartedByExtension;
                apiServerProcess = null;
                apiServerStartedByExtension = false;
            }

            if (process == null || !shouldStop)
            {
                return;
            }

            try
            {
                if (!process.HasExited)
                {
                    process.Kill();
                    await Task.Delay(200);
                }
            }
            catch
            {
                // Ignore shutdown errors
            }
            finally
            {
                process.Dispose();
            }
        }

        private async Task EnsureLogStreamAsync()
        {
            var wsUrl = BuildWebSocketUrl(GetApiUrl());
            if (string.IsNullOrWhiteSpace(wsUrl))
            {
                return;
            }

            await EnsureOutputPaneAsync();

            lock (logSocketLock)
            {
                if (logSocketConnecting)
                {
                    return;
                }
                if (logSocket != null &&
                    (logSocket.State == WebSocketState.Open || logSocket.State == WebSocketState.Connecting) &&
                    string.Equals(logSocketUrl, wsUrl, StringComparison.OrdinalIgnoreCase))
                {
                    return;
                }
                logSocketConnecting = true;
            }

            try
            {
                await StartLogStreamAsync(wsUrl);
            }
            finally
            {
                lock (logSocketLock)
                {
                    logSocketConnecting = false;
                }
            }
        }

        private async Task StartLogStreamAsync(string wsUrl)
        {
            await StopLogStreamAsync();

            var socket = new ClientWebSocket();
            var cts = new CancellationTokenSource();
            try
            {
                await socket.ConnectAsync(new Uri(wsUrl), cts.Token);
            }
            catch (Exception ex)
            {
                LogToOutput($"API log stream error: {ex.Message}");
                socket.Dispose();
                ScheduleLogStreamReconnect(wsUrl);
                return;
            }

            lock (logSocketLock)
            {
                logSocket = socket;
                logSocketCts = cts;
                logSocketUrl = wsUrl;
                logSocketManualClose = false;
                logSocketReconnectAttempts = 0;
            }

            LogToOutput("API log stream connected");
            logSocketTask = Task.Run(() => ReadLogStreamAsync(socket, cts.Token));
        }

        private async Task StopLogStreamAsync()
        {
            ClientWebSocket socketToClose = null;
            CancellationTokenSource ctsToCancel = null;

            lock (logSocketLock)
            {
                socketToClose = logSocket;
                ctsToCancel = logSocketCts;
                logSocket = null;
                logSocketCts = null;
                logSocketUrl = null;
                logSocketManualClose = true;
            }

            if (ctsToCancel != null)
            {
                ctsToCancel.Cancel();
            }

            if (socketToClose != null)
            {
                try
                {
                    if (socketToClose.State == WebSocketState.Open)
                    {
                        await socketToClose.CloseAsync(WebSocketCloseStatus.NormalClosure, "Closing", CancellationToken.None);
                    }
                }
                catch
                {
                    // Ignore shutdown errors
                }
                finally
                {
                    socketToClose.Dispose();
                }
            }
        }

        private async Task ReadLogStreamAsync(ClientWebSocket socket, CancellationToken token)
        {
            var buffer = new ArraySegment<byte>(new byte[4096]);
            var builder = new StringBuilder();

            try
            {
                while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
                {
                    var result = await socket.ReceiveAsync(buffer, token);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        break;
                    }

                    builder.Append(Encoding.UTF8.GetString(buffer.Array, 0, result.Count));
                    if (result.EndOfMessage)
                    {
                        var message = builder.ToString();
                        builder.Clear();
                        HandleLogStreamMessage(message);
                    }
                }
            }
            catch (OperationCanceledException)
            {
                // Expected on shutdown
            }
            catch (Exception ex)
            {
                LogToOutput($"API log stream error: {ex.Message}");
            }
            finally
            {
                LogToOutput("API log stream disconnected");
                if (!logSocketManualClose)
                {
                    ScheduleLogStreamReconnect(logSocketUrl);
                }
            }
        }

        private void HandleLogStreamMessage(string message)
        {
            if (string.IsNullOrWhiteSpace(message))
            {
                return;
            }

            try
            {
                var payload = JObject.Parse(message);
                var type = payload["type"]?.ToString();

                if (string.Equals(type, "log", StringComparison.OrdinalIgnoreCase))
                {
                    var stream = payload["stream"]?.ToString()?.ToUpperInvariant() ?? "LOG";
                    var line = payload["message"]?.ToString() ?? string.Empty;
                    LogToOutput($"[{stream}] {line}");
                    return;
                }

                if (string.Equals(type, "task_completed", StringComparison.OrdinalIgnoreCase))
                {
                    var taskId = payload["task_id"]?.ToString() ?? "unknown";
                    LogToOutput($"Task completed: {taskId}");
                    return;
                }

                if (string.Equals(type, "task_failed", StringComparison.OrdinalIgnoreCase))
                {
                    var taskId = payload["task_id"]?.ToString() ?? "unknown";
                    var error = payload["error"]?.ToString() ?? "unknown error";
                    LogToOutput($"Task failed: {taskId} - {error}");
                    return;
                }

                LogToOutput(message);
            }
            catch (JsonException)
            {
                LogToOutput(message);
            }
        }

        private void ScheduleLogStreamReconnect(string wsUrl)
        {
            if (string.IsNullOrWhiteSpace(wsUrl))
            {
                return;
            }

            lock (logSocketLock)
            {
                if (logSocketReconnectTask != null && !logSocketReconnectTask.IsCompleted)
                {
                    return;
                }
            }

            var delayMs = RevIdeHelpers.ComputeReconnectDelay(logSocketReconnectAttempts);
            logSocketReconnectAttempts += 1;

            logSocketReconnectTask = Task.Run(async () =>
            {
                await Task.Delay(delayMs);
                await EnsureLogStreamAsync();
            });
        }

        private static string BuildWebSocketUrl(string apiUrl)
        {
            return RevIdeHelpers.BuildWebSocketUrl(apiUrl);
        }
    }
}
