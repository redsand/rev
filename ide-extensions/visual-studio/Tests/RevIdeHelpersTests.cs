using System;
using RevExtension.Utilities;
using Xunit;

namespace RevExtension.Tests
{
    public class RevIdeHelpersTests
    {
        [Fact]
        public void BuildWebSocketUrl_UsesWsScheme()
        {
            var result = RevIdeHelpers.BuildWebSocketUrl("http://127.0.0.1:8765");
            Assert.Equal("ws://127.0.0.1:8765/ws", result);
        }

        [Fact]
        public void BuildWebSocketUrl_UsesWssScheme()
        {
            var result = RevIdeHelpers.BuildWebSocketUrl("https://example.test/api");
            Assert.Equal("wss://example.test/ws", result);
        }

        [Fact]
        public void ComputeReconnectDelay_CapsAtFiveSeconds()
        {
            var delay = RevIdeHelpers.ComputeReconnectDelay(5);
            Assert.Equal(5000, delay);
        }

        [Fact]
        public void GetPythonPathFromEnvironment_UsesEnvOverride()
        {
            Environment.SetEnvironmentVariable("REV_IDE_PYTHON_PATH", "C:\\Python\\python.exe");
            try
            {
                var value = RevIdeHelpers.GetPythonPathFromEnvironment();
                Assert.Equal("C:\\Python\\python.exe", value);
            }
            finally
            {
                Environment.SetEnvironmentVariable("REV_IDE_PYTHON_PATH", null);
            }
        }
    }
}
