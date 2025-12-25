/**
 * Rev VSCode Extension
 *
 * Integrates Rev autonomous AI development system with Visual Studio Code
 */

const vscode = require('vscode');
const axios = require('axios');
const path = require('path');
const { spawn } = require('child_process');
const WebSocket = require('ws');

let lspClient = null;
let apiServerProcess = null;
let lspServerProcess = null;
let outputChannel = null;
let apiWebSocket = null;
let apiWebSocketUrl = null;
let apiWebSocketReconnectTimer = null;
let apiWebSocketReconnectAttempts = 0;
let apiWebSocketManualClose = false;

/**
 * Activate the extension
 */
function activate(context) {
    console.log('Rev extension is now active');

    // Create output channel
    outputChannel = vscode.window.createOutputChannel('Rev');
    context.subscriptions.push(outputChannel);

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('rev.analyzeCode', analyzeCode),
        vscode.commands.registerCommand('rev.generateTests', generateTests),
        vscode.commands.registerCommand('rev.refactorCode', refactorCode),
        vscode.commands.registerCommand('rev.debugCode', debugCode),
        vscode.commands.registerCommand('rev.addDocumentation', addDocumentation),
        vscode.commands.registerCommand('rev.executeTask', executeTask),
        vscode.commands.registerCommand('rev.startLSP', startLSPServer),
        vscode.commands.registerCommand('rev.startAPI', startAPIServer),
        vscode.commands.registerCommand('rev.selectModel', selectModel),
        vscode.commands.registerCommand('rev.showCurrentModel', showCurrentModel)
    );

    // Auto-start servers if configured
    const config = vscode.workspace.getConfiguration('rev');
    if (config.get('autoStartServers')) {
        if (config.get('enableLSP')) {
            startLSPServer();
        }
        startAPIServer();
    }

    outputChannel.appendLine('Rev extension activated');
}

/**
 * Deactivate the extension
 */
function deactivate() {
    if (apiServerProcess) {
        apiServerProcess.kill();
    }
    if (lspServerProcess) {
        lspServerProcess.kill();
    }
    closeApiWebSocket();
    if (outputChannel) {
        outputChannel.dispose();
    }
}

/**
 * Get current file path
 */
function getCurrentFilePath() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showErrorMessage('No active editor');
        return null;
    }
    return editor.document.uri.fsPath;
}

/**
 * Get selected text range
 */
function getSelectedRange() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        return null;
    }
    const selection = editor.selection;
    if (selection.isEmpty) {
        return null;
    }
    return {
        start_line: selection.start.line + 1,
        end_line: selection.end.line + 1
    };
}

/**
 * Make API request to Rev
 */
async function makeAPIRequest(endpoint, data) {
    connectApiWebSocket();
    const config = vscode.workspace.getConfiguration('rev');
    const apiUrl = config.get('apiUrl');
    const timeout = config.get('timeout') * 1000;

    try {
        const response = await axios.post(
            `${apiUrl}${endpoint}`,
            data,
            { timeout }
        );
        return response.data;
    } catch (error) {
        if (error.response) {
            throw new Error(`Rev API error: ${error.response.data.message || error.message}`);
        } else if (error.request) {
            throw new Error('Rev API server is not responding. Please start the Rev API server.');
        } else {
            throw new Error(`Request error: ${error.message}`);
        }
    }
}

function buildApiWebSocketUrl() {
    const config = vscode.workspace.getConfiguration('rev');
    const apiUrl = config.get('apiUrl');
    if (!apiUrl) {
        return null;
    }

    try {
        const url = new URL(apiUrl);
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        url.pathname = '/ws';
        url.search = '';
        url.hash = '';
        return url.toString();
    } catch (error) {
        if (outputChannel) {
            outputChannel.appendLine(`API Error: Invalid apiUrl '${apiUrl}'`);
        }
        return null;
    }
}

function connectApiWebSocket() {
    if (!outputChannel) {
        return;
    }

    const wsUrl = buildApiWebSocketUrl();
    if (!wsUrl) {
        return;
    }

    if (apiWebSocket &&
        (apiWebSocket.readyState === WebSocket.OPEN || apiWebSocket.readyState === WebSocket.CONNECTING) &&
        apiWebSocketUrl === wsUrl) {
        return;
    }

    if (apiWebSocket) {
        apiWebSocketManualClose = true;
        apiWebSocket.close();
        apiWebSocket = null;
    }

    apiWebSocketUrl = wsUrl;
    apiWebSocketManualClose = false;

    try {
        apiWebSocket = new WebSocket(wsUrl);
    } catch (error) {
        outputChannel.appendLine(`API log stream error: ${error.message}`);
        scheduleApiWebSocketReconnect();
        return;
    }

    apiWebSocket.on('open', () => {
        apiWebSocketReconnectAttempts = 0;
        outputChannel.appendLine('API log stream connected');
    });

    apiWebSocket.on('message', (data) => {
        const text = data ? data.toString() : '';
        if (!text) {
            return;
        }
        try {
            const payload = JSON.parse(text);
            handleApiStreamMessage(payload);
        } catch (error) {
            outputChannel.appendLine(text);
        }
    });

    apiWebSocket.on('close', (code, reason) => {
        const detail = reason ? ` (${reason.toString()})` : '';
        outputChannel.appendLine(`API log stream disconnected (code ${code}${detail})`);
        apiWebSocket = null;
        if (!apiWebSocketManualClose) {
            scheduleApiWebSocketReconnect();
        }
    });

    apiWebSocket.on('error', (error) => {
        outputChannel.appendLine(`API log stream error: ${error.message}`);
    });
}

function scheduleApiWebSocketReconnect() {
    if (apiWebSocketReconnectTimer) {
        return;
    }
    const delay = Math.min(5000, 500 * Math.pow(2, apiWebSocketReconnectAttempts));
    apiWebSocketReconnectTimer = setTimeout(() => {
        apiWebSocketReconnectTimer = null;
        apiWebSocketReconnectAttempts += 1;
        connectApiWebSocket();
    }, delay);
}

function closeApiWebSocket() {
    if (apiWebSocketReconnectTimer) {
        clearTimeout(apiWebSocketReconnectTimer);
        apiWebSocketReconnectTimer = null;
    }
    if (apiWebSocket) {
        apiWebSocketManualClose = true;
        apiWebSocket.close();
        apiWebSocket = null;
    }
}

function handleApiStreamMessage(payload) {
    if (!payload || typeof payload !== 'object') {
        return;
    }

    if (payload.type === 'log') {
        const stream = payload.stream ? payload.stream.toUpperCase() : 'LOG';
        const message = payload.message ?? '';
        if (message === '') {
            outputChannel.appendLine('');
            return;
        }
        outputChannel.appendLine(`[${stream}] ${message}`);
        return;
    }

    if (payload.type === 'task_completed') {
        outputChannel.appendLine(`Task completed: ${payload.task_id || 'unknown'}`);
        return;
    }

    if (payload.type === 'task_failed') {
        outputChannel.appendLine(`Task failed: ${payload.task_id || 'unknown'} - ${payload.error || 'unknown error'}`);
        return;
    }
}

/**
 * Show task result
 */
function showTaskResult(result, title) {
    if (result.status === 'error') {
        vscode.window.showErrorMessage(`Rev: ${result.message}`);
        outputChannel.appendLine(`Error: ${result.message}`);
    } else {
        vscode.window.showInformationMessage(`Rev: ${title} started successfully`);
        if (result.task_id) {
            outputChannel.appendLine(`Task ID: ${result.task_id}`);
        }
        if (result.result) {
            outputChannel.appendLine(`Result: ${JSON.stringify(result.result, null, 2)}`);
        }
    }
    outputChannel.show();
}

/**
 * Analyze code command
 */
async function analyzeCode() {
    const filePath = getCurrentFilePath();
    if (!filePath) return;

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Rev: Analyzing code...',
                cancellable: false
            },
            async () => {
                outputChannel.appendLine(`Analyzing: ${filePath}`);
                const result = await makeAPIRequest('/api/v1/analyze', { file_path: filePath });
                showTaskResult(result, 'Code analysis');
            }
        );
    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error: ${error.message}`);
    }
}

/**
 * Generate tests command
 */
async function generateTests() {
    const filePath = getCurrentFilePath();
    if (!filePath) return;

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Rev: Generating tests...',
                cancellable: false
            },
            async () => {
                outputChannel.appendLine(`Generating tests for: ${filePath}`);
                const result = await makeAPIRequest('/api/v1/test', { file_path: filePath });
                showTaskResult(result, 'Test generation');
            }
        );
    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error: ${error.message}`);
    }
}

/**
 * Refactor code command
 */
async function refactorCode() {
    const filePath = getCurrentFilePath();
    if (!filePath) return;

    const range = getSelectedRange();

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Rev: Refactoring code...',
                cancellable: false
            },
            async () => {
                outputChannel.appendLine(`Refactoring: ${filePath}`);
                const data = { file_path: filePath };
                if (range) {
                    data.start_line = range.start_line;
                    data.end_line = range.end_line;
                    outputChannel.appendLine(`  Lines: ${range.start_line}-${range.end_line}`);
                }
                const result = await makeAPIRequest('/api/v1/refactor', data);
                showTaskResult(result, 'Code refactoring');
            }
        );
    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error: ${error.message}`);
    }
}

/**
 * Debug code command
 */
async function debugCode() {
    const filePath = getCurrentFilePath();
    if (!filePath) return;

    // Optionally get error message from user
    const errorMessage = await vscode.window.showInputBox({
        prompt: 'Enter error message (optional)',
        placeHolder: 'Leave empty to auto-detect issues'
    });

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Rev: Debugging code...',
                cancellable: false
            },
            async () => {
                outputChannel.appendLine(`Debugging: ${filePath}`);
                const data = { file_path: filePath };
                if (errorMessage) {
                    data.error_message = errorMessage;
                    outputChannel.appendLine(`  Error: ${errorMessage}`);
                }
                const result = await makeAPIRequest('/api/v1/debug', data);
                showTaskResult(result, 'Code debugging');
            }
        );
    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error: ${error.message}`);
    }
}

/**
 * Add documentation command
 */
async function addDocumentation() {
    const filePath = getCurrentFilePath();
    if (!filePath) return;

    const range = getSelectedRange();

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Rev: Adding documentation...',
                cancellable: false
            },
            async () => {
                outputChannel.appendLine(`Adding documentation to: ${filePath}`);
                const data = { file_path: filePath };
                if (range) {
                    data.start_line = range.start_line;
                    data.end_line = range.end_line;
                    outputChannel.appendLine(`  Lines: ${range.start_line}-${range.end_line}`);
                }
                const result = await makeAPIRequest('/api/v1/document', data);
                showTaskResult(result, 'Documentation');
            }
        );
    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error: ${error.message}`);
    }
}

/**
 * Execute custom task command
 */
async function executeTask() {
    const task = await vscode.window.showInputBox({
        prompt: 'Enter Rev task description',
        placeHolder: 'e.g., Add error handling to all API endpoints'
    });

    if (!task) {
        return;
    }

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'Rev: Executing task...',
                cancellable: false
            },
            async () => {
                outputChannel.appendLine(`Executing task: ${task}`);
                const result = await makeAPIRequest('/api/v1/execute', { task });
                showTaskResult(result, 'Task execution');
            }
        );
    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error: ${error.message}`);
    }
}

/**
 * Start LSP server
 */
function startLSPServer() {
    if (lspServerProcess) {
        vscode.window.showInformationMessage('Rev LSP server is already running');
        return;
    }

    const config = vscode.workspace.getConfiguration('rev');
    const pythonPath = config.get('pythonPath');

    try {
        lspServerProcess = spawn(pythonPath, ['-m', 'rev.ide.lsp_server'], {
            cwd: vscode.workspace.rootPath
        });

        lspServerProcess.stdout.on('data', (data) => {
            outputChannel.appendLine(`LSP: ${data.toString()}`);
        });

        lspServerProcess.stderr.on('data', (data) => {
            outputChannel.appendLine(`LSP Error: ${data.toString()}`);
        });

        lspServerProcess.on('close', (code) => {
            outputChannel.appendLine(`LSP server exited with code ${code}`);
            lspServerProcess = null;
        });

        vscode.window.showInformationMessage('Rev LSP server started');
        outputChannel.appendLine('Rev LSP server started');
    } catch (error) {
        vscode.window.showErrorMessage(`Failed to start LSP server: ${error.message}`);
        outputChannel.appendLine(`LSP Error: ${error.message}`);
    }
}

/**
 * Start API server
 */
function startAPIServer() {
    if (apiServerProcess) {
        vscode.window.showInformationMessage('Rev API server is already running');
        return;
    }

    const config = vscode.workspace.getConfiguration('rev');
    const pythonPath = config.get('pythonPath');

    try {
        apiServerProcess = spawn(pythonPath, ['-m', 'rev.ide.api_server'], {
            cwd: vscode.workspace.rootPath
        });

        connectApiWebSocket();

        apiServerProcess.stdout.on('data', (data) => {
            outputChannel.appendLine(`API: ${data.toString()}`);
        });

        apiServerProcess.stderr.on('data', (data) => {
            outputChannel.appendLine(`API Error: ${data.toString()}`);
        });

        apiServerProcess.on('close', (code) => {
            outputChannel.appendLine(`API server exited with code ${code}`);
            apiServerProcess = null;
        });

        vscode.window.showInformationMessage('Rev API server started');
        outputChannel.appendLine('Rev API server started');
    } catch (error) {
        vscode.window.showErrorMessage(`Failed to start API server: ${error.message}`);
        outputChannel.appendLine(`API Error: ${error.message}`);
    }
}

/**
 * Select model command
 */
async function selectModel() {
    try {
        const config = vscode.workspace.getConfiguration('rev');
        const apiUrl = config.get('apiUrl');

        // Fetch available models
        const modelsResponse = await axios.get(`${apiUrl}/api/v1/models`);

        if (modelsResponse.data.status === 'error') {
            vscode.window.showErrorMessage(`Rev: ${modelsResponse.data.message}`);
            return;
        }

        const models = modelsResponse.data.models || [];

        if (models.length === 0) {
            vscode.window.showWarningMessage('Rev: No models available');
            return;
        }

        // Show quick pick with available models
        const selectedModel = await vscode.window.showQuickPick(models, {
            placeHolder: 'Select a model to use',
            title: 'Rev: Select Model'
        });

        if (!selectedModel) {
            return;
        }

        // Select the model
        const selectResponse = await axios.post(
            `${apiUrl}/api/v1/models/select`,
            { model_name: selectedModel }
        );

        if (selectResponse.data.status === 'success') {
            vscode.window.showInformationMessage(`Rev: Model changed to ${selectedModel}`);
            outputChannel.appendLine(`Model changed to: ${selectedModel}`);
        } else {
            vscode.window.showErrorMessage(`Rev: ${selectResponse.data.message}`);
        }

    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error selecting model: ${error.message}`);
    }
}

/**
 * Show current model command
 */
async function showCurrentModel() {
    try {
        const config = vscode.workspace.getConfiguration('rev');
        const apiUrl = config.get('apiUrl');

        const response = await axios.get(`${apiUrl}/api/v1/models/current`);

        if (response.data.status === 'success') {
            const currentModel = response.data.current_model;
            const message = `Current Rev Configuration:\n` +
                `Execution Model: ${currentModel.execution_model}\n` +
                `Planning Model: ${currentModel.planning_model}\n` +
                `Research Model: ${currentModel.research_model}\n` +
                `Provider: ${currentModel.provider}`;

            vscode.window.showInformationMessage(message);
            outputChannel.appendLine(message);
        } else {
            vscode.window.showErrorMessage(`Rev: ${response.data.message}`);
        }

    } catch (error) {
        vscode.window.showErrorMessage(`Rev: ${error.message}`);
        outputChannel.appendLine(`Error getting current model: ${error.message}`);
    }
}

module.exports = {
    activate,
    deactivate
};
