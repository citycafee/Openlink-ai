"use strict";

const vscode = require("vscode");
const path = require("path");
const fs = require("fs");
const net = require("net");
const os = require("os");

const HOST = "127.0.0.1";
const PORT = 8377;
const URL = `http://${HOST}:${PORT}/`;
const CHAT_TERMINAL = "Openlink AI";
const WEB_TERMINAL = "Openlink AI Web";
const KNOWN_PROJECT = "E:\\OpenCodeTemp\\openlink AI";
const TRIGGER_FILE = path.join(
	process.env.LOCALAPPDATA || process.env.APPDATA || os.homedir(),
	"openlink",
	"vscode_autostart"
);
const TRIGGER_MAX_AGE_MS = 5 * 60 * 1000;
const TRIGGER_POLL_MS = 700;

function cfg() {
	return vscode.workspace.getConfiguration("openlink");
}

function pythonPath() {
	return cfg().get("pythonPath") || "python";
}

function projectPath() {
	const configured = cfg().get("projectPath");
	if (configured && fs.existsSync(path.join(configured, "run.py"))) {
		return configured;
	}
	const folders = vscode.workspace.workspaceFolders || [];
	for (const folder of folders) {
		if (fs.existsSync(path.join(folder.uri.fsPath, "run.py"))) {
			return folder.uri.fsPath;
		}
	}
	if (fs.existsSync(path.join(KNOWN_PROJECT, "run.py"))) {
		return KNOWN_PROJECT;
	}
	return null;
}

function findTerminal(name) {
	return vscode.window.terminals.find((t) => t.name === name);
}

function portOpen() {
	return new Promise((resolve) => {
		const socket = net.connect({ host: HOST, port: PORT });
		socket.setTimeout(700);
		socket.once("connect", () => {
			socket.destroy();
			resolve(true);
		});
		const fail = () => {
			socket.destroy();
			resolve(false);
		};
		socket.once("error", fail);
		socket.once("timeout", fail);
	});
}

function waitForPort(timeoutMs) {
	const deadline = Date.now() + timeoutMs;
	return (async () => {
		while (Date.now() < deadline) {
			if (await portOpen()) return true;
			await new Promise((r) => setTimeout(r, 400));
		}
		return false;
	})();
}

function requireProject() {
	const dir = projectPath();
	if (!dir) {
		vscode.window
			.showErrorMessage(
				"Openlink: could not find run.py. Set \"openlink.projectPath\" in Settings.",
				"Open Settings"
			)
			.then((choice) => {
				if (choice === "Open Settings") {
					vscode.commands.executeCommand(
						"workbench.action.openSettings",
						"openlink.projectPath"
					);
				}
			});
		return null;
	}
	return dir;
}

function quote(arg) {
	return /^[A-Za-z0-9_\\/:.\-]+$/.test(arg) ? arg : `"${arg}"`;
}

async function openChat() {
	const dir = requireProject();
	if (!dir) return;

	const existing = findTerminal(CHAT_TERMINAL);
	if (existing) {
		existing.show();
		return;
	}

	const terminal = vscode.window.createTerminal({
		name: CHAT_TERMINAL,
		cwd: dir,
		iconPath: {
			light: vscode.Uri.file(
				path.join(__dirname, "images", "button-dark.svg")
			),
			dark: vscode.Uri.file(
				path.join(__dirname, "images", "button-light.svg")
			),
		},
		env: { OPENLINK_CALLER: "vscode" },
	});
	terminal.show();
	terminal.sendText(`${quote(pythonPath())} run.py chat`);
}

async function openWeb() {
	const dir = requireProject();
	if (!dir) return;

	if (await portOpen()) {
		await vscode.env.openExternal(vscode.Uri.parse(URL));
		return;
	}

	let terminal = findTerminal(WEB_TERMINAL);
	if (!terminal) {
		terminal = vscode.window.createTerminal({
			name: WEB_TERMINAL,
			cwd: dir,
			iconPath: {
				light: vscode.Uri.file(
					path.join(__dirname, "images", "button-dark.svg")
				),
				dark: vscode.Uri.file(
					path.join(__dirname, "images", "button-light.svg")
				),
			},
			env: { OPENLINK_CALLER: "vscode" },
		});
		terminal.show();
		terminal.sendText(`${quote(pythonPath())} -u web_server.py`);
	} else {
		terminal.show();
	}

	const ok = await waitForPort(30000);
	if (ok) {
		await vscode.env.openExternal(vscode.Uri.parse(URL));
	} else {
		vscode.window.showErrorMessage(
			`Openlink: server did not come up on ${URL} (check the "${WEB_TERMINAL}" terminal).`
		);
	}
}

async function addFilepathToTerminal() {
	const editor = vscode.window.activeTextEditor;
	if (!editor) {
		vscode.window.showInformationMessage("Openlink: no active file.");
		return;
	}
	const file = editor.document.uri.fsPath;
	const terminal = findTerminal(CHAT_TERMINAL);
	if (!terminal) {
		await openChat();
		return;
	}
	terminal.sendText(file, false);
	terminal.show();
}

function folderMatchesWorkspace(folder) {
	const target = path.resolve(folder).toLowerCase().replace(/[\\/]+$/, "");
	const folders = vscode.workspace.workspaceFolders || [];
	return folders.some(
		(f) =>
			path.resolve(f.uri.fsPath).toLowerCase().replace(/[\\/]+$/, "") === target
	);
}

function handleTrigger() {
	let stat, raw;
	try {
		stat = fs.statSync(TRIGGER_FILE);
		raw = fs.readFileSync(TRIGGER_FILE, "utf8");
	} catch (e) {
		return;
	}
	if (Date.now() - stat.mtimeMs > TRIGGER_MAX_AGE_MS) {
		try {
			fs.unlinkSync(TRIGGER_FILE);
		} catch (e) {}
		return;
	}

	let data;
	try {
		data = JSON.parse(raw);
	} catch (e) {
		data = { command: String(raw).trim() };
	}
	if (!data || typeof data !== "object") return;

	const folder = typeof data.folder === "string" ? data.folder : "";
	if (folder) {
		if (!folderMatchesWorkspace(folder)) return;
	} else if (!vscode.window.state.focused) {
		return;
	}

	try {
		fs.unlinkSync(TRIGGER_FILE);
	} catch (e) {
		return;
	}

	const command = String(data.command || "chat").toLowerCase();
	if (command === "web" || command === "start-web") {
		openWeb();
	} else {
		openChat();
	}
}

function startTriggerPoller(context) {
	const tick = () => {
		try {
			handleTrigger();
		} catch (e) {
			console.error("openlink trigger:", e);
		}
	};
	tick();
	const timer = setInterval(tick, TRIGGER_POLL_MS);
	context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

function createStatusItem(context) {
	const item = vscode.window.createStatusBarItem(
		vscode.StatusBarAlignment.Right,
		100
	);
	item.command = "openlink.openWeb";
	item.name = "Openlink";

	const refresh = async () => {
		const up = await portOpen();
		item.text = up ? "$(globe) Openlink" : "$(circle-slash) Openlink";
		item.tooltip = up
			? `Openlink web server running — click to open ${URL}`
			: "Openlink web server not running — click to start it";
		item.show();
	};

	refresh();
	const timer = setInterval(refresh, 5000);
	context.subscriptions.push({ dispose: () => clearInterval(timer) });
	context.subscriptions.push(item);
}

function activate(context) {
	context.subscriptions.push(
		vscode.commands.registerCommand("openlink.openChat", openChat),
		vscode.commands.registerCommand("openlink.openWeb", openWeb),
		vscode.commands.registerCommand(
			"openlink.addFilepathToTerminal",
			addFilepathToTerminal
		)
	);
	startTriggerPoller(context);
	createStatusItem(context);
}

function deactivate() {}

module.exports = { activate, deactivate };
