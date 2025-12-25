using System;
using System.ComponentModel.Design;
using Microsoft.VisualStudio.Shell;
using Task = System.Threading.Tasks.Task;

namespace RevExtension.Commands
{
    /// <summary>
    /// Command to analyze code using Rev
    /// </summary>
    internal sealed class AnalyzeCodeCommand : BaseRevCommand
    {
        public const int CommandId = 0x0100;
        public static readonly Guid CommandSet = new Guid("f1e2d3c4-b5a6-4c5d-8e9f-0a1b2c3d4e5f");

        private AnalyzeCodeCommand(AsyncPackage package) : base(package)
        {
        }

        public static async Task InitializeAsync(AsyncPackage package)
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync(package.DisposalToken);

            var commandService = await package.GetServiceAsync(typeof(IMenuCommandService)) as OleMenuCommandService;
            if (commandService != null)
            {
                var menuCommandID = new CommandID(CommandSet, CommandId);
                var menuItem = new MenuCommand(
                    (sender, e) => _ = ExecuteAsync(package),
                    menuCommandID
                );
                commandService.AddCommand(menuItem);
            }
        }

        private static async Task ExecuteAsync(AsyncPackage package)
        {
            var command = new AnalyzeCodeCommand(package);
            await command.ExecuteInternalAsync();
        }

        private async Task ExecuteInternalAsync()
        {
            try
            {
                var filePath = await GetActiveDocumentPathAsync();
                LogToOutput($"Analyzing: {filePath}");

                var result = await MakeApiRequestAsync("/api/v1/analyze", new { file_path = filePath });

                if (result["status"]?.ToString() == "error")
                {
                    await ShowMessageAsync($"Error: {result["message"]}", true);
                }
                else
                {
                    await ShowMessageAsync("Code analysis started. Check output window for results.");
                    LogToOutput($"Result: {result}");
                }
            }
            catch (Exception ex)
            {
                await ShowMessageAsync($"Error: {ex.Message}", true);
                LogToOutput($"Error: {ex}");
            }
        }
    }
}
