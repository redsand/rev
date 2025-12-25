using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using EnvDTE;
using Microsoft.VisualStudio.Shell;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace RevExtension.Commands
{
    /// <summary>
    /// Base class for Rev commands
    /// </summary>
    public abstract class BaseRevCommand
    {
        protected readonly AsyncPackage package;
        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(300) };

        protected BaseRevCommand(AsyncPackage package)
        {
            this.package = package ?? throw new ArgumentNullException(nameof(package));
        }

        /// <summary>
        /// Gets the API URL from settings
        /// </summary>
        protected string GetApiUrl()
        {
            // TODO: Load from settings
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
            // TODO: Implement output window logging
            System.Diagnostics.Debug.WriteLine($"[Rev] {message}");
        }
    }
}
