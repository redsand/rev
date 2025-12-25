using System;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.VisualStudio.Shell;
using Task = System.Threading.Tasks.Task;

namespace RevExtension
{
    /// <summary>
    /// Rev Extension Package for Visual Studio
    /// </summary>
    [PackageRegistration(UseManagedResourcesOnly = true, AllowsBackgroundLoading = true)]
    [Guid(RevPackage.PackageGuidString)]
    [ProvideMenuResource("Menus.ctmenu", 1)]
    [ProvideAutoLoad(Microsoft.VisualStudio.Shell.Interop.UIContextGuids80.SolutionExists, PackageAutoLoadFlags.BackgroundLoad)]
    public sealed class RevPackage : AsyncPackage
    {
        public const string PackageGuidString = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d";

        /// <summary>
        /// Initialization of the package
        /// </summary>
        protected override async Task InitializeAsync(CancellationToken cancellationToken, IProgress<ServiceProgressData> progress)
        {
            await this.JoinableTaskFactory.SwitchToMainThreadAsync(cancellationToken);

            // Initialize commands
            await Commands.AnalyzeCodeCommand.InitializeAsync(this);
            await Commands.GenerateTestsCommand.InitializeAsync(this);
            await Commands.RefactorCodeCommand.InitializeAsync(this);
            await Commands.DebugCodeCommand.InitializeAsync(this);
            await Commands.AddDocumentationCommand.InitializeAsync(this);
            await Commands.ExecuteTaskCommand.InitializeAsync(this);
        }
    }
}
