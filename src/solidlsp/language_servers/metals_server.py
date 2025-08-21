"""
Provides Scala specific instantiation of the LanguageServer class using Metals.
Contains various configurations and settings specific to Scala/Metals.
"""

import dataclasses
import logging
import os
import pathlib
import shutil
import subprocess

from overrides import override

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.ls_logger import LanguageServerLogger
from solidlsp.ls_utils import FileUtils, PlatformUtils
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.lsp_protocol_handler.server import ProcessLaunchInfo
from solidlsp.settings import SolidLSPSettings


@dataclasses.dataclass
class MetalsRuntimeDependencyPaths:
    """
    Stores the paths to the runtime dependencies of Metals Language Server
    """

    java_path: str
    java_home_path: str
    metals_classpath: str  # Full classpath with all dependencies


class MetalsLanguageServer(SolidLanguageServer):
    """
    Provides Scala specific instantiation of the LanguageServer class using Metals.
    """

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # For Scala projects, we should ignore:
        # - target: SBT/Maven build output directory
        # - .bsp: Build Server Protocol configuration
        # - .metals: Metals-specific metadata
        # - node_modules: if the project has JavaScript components
        # - dist/build: common output directories
        return super().is_ignored_dirname(dirname) or dirname in ["target", ".bsp", ".metals", "node_modules", "dist", "build"]

    def __init__(
        self,
        config: LanguageServerConfig,
        logger: LanguageServerLogger,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ):
        """
        Creates a Metals Language Server instance.
        This class is not meant to be instantiated directly. Use LanguageServer.create() instead.
        """
        runtime_dependency_paths = self._setup_runtime_dependencies(logger, config, solidlsp_settings)
        self.runtime_dependency_paths = runtime_dependency_paths

        # Create command to execute Metals with Java using full classpath
        cmd = f'"{self.runtime_dependency_paths.java_path}" -cp "{self.runtime_dependency_paths.metals_classpath}" scala.meta.metals.Main'

        # Set environment variables including JAVA_HOME
        proc_env = {"JAVA_HOME": self.runtime_dependency_paths.java_home_path}

        super().__init__(
            config,
            logger,
            repository_root_path,
            ProcessLaunchInfo(cmd=cmd, env=proc_env, cwd=repository_root_path),
            "scala",
            solidlsp_settings,
        )

    @classmethod
    def _setup_runtime_dependencies(
        cls, logger: LanguageServerLogger, config: LanguageServerConfig, solidlsp_settings: SolidLSPSettings
    ) -> MetalsRuntimeDependencyPaths:
        """
        Setup runtime dependencies for Metals Language Server and return the paths.
        """
        platform_id = PlatformUtils.get_platform_id()

        # Verify platform support
        assert (
            platform_id.value.startswith("win-") or platform_id.value.startswith("linux-") or platform_id.value.startswith("osx-")
        ), "Only Windows, Linux and macOS platforms are supported for Scala/Metals at the moment"

        # Runtime dependency information
        runtime_dependencies = {
            "metals": {
                "id": "Metals",
                "description": "Metals Language Server for Scala",
                # Using Coursier to download Metals - this ensures we get the correct JAR
                "coursier_artifact": "org.scalameta:metals_2.13:1.6.2",
                "filename": "metals.jar",
            },
            "java": {
                "win-x64": {
                    "url": "https://github.com/redhat-developer/vscode-java/releases/download/v1.42.0/java-win32-x64-1.42.0-561.vsix",
                    "archiveType": "zip",
                    "java_home_path": "extension/jre/21.0.7-win32-x86_64",
                    "java_path": "extension/jre/21.0.7-win32-x86_64/bin/java.exe",
                },
                "linux-x64": {
                    "url": "https://github.com/redhat-developer/vscode-java/releases/download/v1.42.0/java-linux-x64-1.42.0-561.vsix",
                    "archiveType": "zip",
                    "java_home_path": "extension/jre/21.0.7-linux-x86_64",
                    "java_path": "extension/jre/21.0.7-linux-x86_64/bin/java",
                },
                "linux-arm64": {
                    "url": "https://github.com/redhat-developer/vscode-java/releases/download/v1.42.0/java-linux-arm64-1.42.0-561.vsix",
                    "archiveType": "zip",
                    "java_home_path": "extension/jre/21.0.7-linux-aarch64",
                    "java_path": "extension/jre/21.0.7-linux-aarch64/bin/java",
                },
                "osx-x64": {
                    "url": "https://github.com/redhat-developer/vscode-java/releases/download/v1.42.0/java-darwin-x64-1.42.0-561.vsix",
                    "archiveType": "zip",
                    "java_home_path": "extension/jre/21.0.7-macosx-x86_64",
                    "java_path": "extension/jre/21.0.7-macosx-x86_64/bin/java",
                },
                "osx-arm64": {
                    "url": "https://github.com/redhat-developer/vscode-java/releases/download/v1.42.0/java-darwin-arm64-1.42.0-561.vsix",
                    "archiveType": "zip",
                    "java_home_path": "extension/jre/21.0.7-macosx-aarch64",
                    "java_path": "extension/jre/21.0.7-macosx-aarch64/bin/java",
                },
            },
        }

        metals_dependency = runtime_dependencies["metals"]
        java_dependency = runtime_dependencies["java"][platform_id.value]

        # Setup paths for dependencies
        static_dir = os.path.join(cls.ls_resources_dir(solidlsp_settings), "metals_language_server")
        os.makedirs(static_dir, exist_ok=True)

        # Setup Java paths
        java_dir = os.path.join(static_dir, "java")
        os.makedirs(java_dir, exist_ok=True)

        java_home_path = os.path.join(java_dir, java_dependency["java_home_path"])
        java_path = os.path.join(java_dir, java_dependency["java_path"])

        # Download and extract Java if not exists
        if not os.path.exists(java_path):
            logger.log(f"Downloading Java for {platform_id.value}...", logging.INFO)
            FileUtils.download_and_extract_archive(logger, java_dependency["url"], java_dir, java_dependency["archiveType"])
            # Make Java executable
            if not platform_id.value.startswith("win-"):
                os.chmod(java_path, 0o755)

        assert os.path.exists(java_path), f"Java executable not found at {java_path}"

        # Setup Metals classpath file
        metals_classpath_file = os.path.join(static_dir, "metals_classpath.txt")

        # Download Metals and its dependencies if not exists
        if not os.path.exists(metals_classpath_file):
            logger.log("Downloading Metals Language Server and dependencies...", logging.INFO)
            # First, check if coursier is available
            if shutil.which("cs") or shutil.which("coursier"):
                # Use coursier if available
                coursier_cmd = "cs" if shutil.which("cs") else "coursier"
                try:
                    result = subprocess.run(
                        [coursier_cmd, "fetch", "--classpath", metals_dependency["coursier_artifact"]],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    # Coursier returns the full classpath with all dependencies
                    classpath = result.stdout.strip()

                    # Save the classpath for future use
                    with open(metals_classpath_file, "w") as f:
                        f.write(classpath)

                    logger.log(f"Downloaded Metals with full classpath: {len(classpath.split(':'))} JAR files", logging.INFO)

                    # Verify at least the main Metals JAR exists
                    jar_paths = classpath.split(":" if ":" in classpath else ";")
                    metals_found = any("metals" in jar_path.lower() for jar_path in jar_paths)
                    if not metals_found:
                        raise FileNotFoundError("Metals JAR not found in classpath")

                except subprocess.CalledProcessError as e:
                    logger.log(f"Failed to download Metals using Coursier: {e}", logging.ERROR)
                    # For fallback, we need to construct a minimal classpath
                    # This is not ideal as Metals has many dependencies
                    raise RuntimeError(
                        "Coursier failed to download Metals. Please install Coursier "
                        "or ensure it's in your PATH for proper Scala LSP support."
                    )
            else:
                # Without Coursier, we can't easily get all dependencies
                raise RuntimeError(
                    "Coursier is required for Scala/Metals support. " "Please install it from https://get-coursier.io/docs/cli-installation"
                )

        # Read the saved classpath
        with open(metals_classpath_file) as f:
            metals_classpath = f.read().strip()

        return MetalsRuntimeDependencyPaths(java_path=java_path, java_home_path=java_home_path, metals_classpath=metals_classpath)

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """
        Returns the initialize params for the Metals Language Server.
        """
        if not os.path.isabs(repository_absolute_path):
            repository_absolute_path = os.path.abspath(repository_absolute_path)

        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        initialize_params = {
            "clientInfo": {"name": "Multilspy Scala Client", "version": "1.0.0"},
            "locale": "en",
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "capabilities": {
                "workspace": {
                    "applyEdit": True,
                    "workspaceEdit": {
                        "documentChanges": True,
                        "resourceOperations": ["create", "rename", "delete"],
                        "failureHandling": "textOnlyTransactional",
                        "normalizesLineEndings": True,
                        "changeAnnotationSupport": {"groupsOnLabel": True},
                    },
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    "didChangeWatchedFiles": {"dynamicRegistration": True, "relativePatternSupport": True},
                    "symbol": {
                        "dynamicRegistration": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                        "tagSupport": {"valueSet": [1]},
                        "resolveSupport": {"properties": ["location.range"]},
                    },
                    "codeLens": {"refreshSupport": True},
                    "executeCommand": {"dynamicRegistration": True},
                    "configuration": True,
                    "workspaceFolders": True,
                    "semanticTokens": {"refreshSupport": True},
                    "fileOperations": {
                        "dynamicRegistration": True,
                        "didCreate": True,
                        "didRename": True,
                        "didDelete": True,
                        "willCreate": True,
                        "willRename": True,
                        "willDelete": True,
                    },
                    "inlineValue": {"refreshSupport": True},
                    "inlayHint": {"refreshSupport": True},
                    "diagnostics": {"refreshSupport": True},
                },
                "textDocument": {
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "versionSupport": False,
                        "tagSupport": {"valueSet": [1, 2]},
                        "codeDescriptionSupport": True,
                        "dataSupport": True,
                    },
                    "synchronization": {
                        "dynamicRegistration": True,
                        "willSave": True,
                        "willSaveWaitUntil": True,
                        "didSave": True,
                    },
                    "completion": {
                        "dynamicRegistration": True,
                        "contextSupport": True,
                        "completionItem": {
                            "snippetSupport": True,
                            "commitCharactersSupport": True,
                            "documentationFormat": ["markdown", "plaintext"],
                            "deprecatedSupport": True,
                            "preselectSupport": True,
                            "tagSupport": {"valueSet": [1]},
                            "insertReplaceSupport": False,
                            "resolveSupport": {"properties": ["documentation", "detail", "additionalTextEdits"]},
                            "insertTextModeSupport": {"valueSet": [1, 2]},
                            "labelDetailsSupport": True,
                        },
                        "insertTextMode": 2,
                        "completionItemKind": {
                            "valueSet": [
                                1,
                                2,
                                3,
                                4,
                                5,
                                6,
                                7,
                                8,
                                9,
                                10,
                                11,
                                12,
                                13,
                                14,
                                15,
                                16,
                                17,
                                18,
                                19,
                                20,
                                21,
                                22,
                                23,
                                24,
                                25,
                            ]
                        },
                        "completionList": {"itemDefaults": ["commitCharacters", "editRange", "insertTextFormat", "insertTextMode"]},
                    },
                    "hover": {"dynamicRegistration": True, "contentFormat": ["markdown", "plaintext"]},
                    "signatureHelp": {
                        "dynamicRegistration": True,
                        "signatureInformation": {
                            "documentationFormat": ["markdown", "plaintext"],
                            "parameterInformation": {"labelOffsetSupport": True},
                            "activeParameterSupport": True,
                        },
                        "contextSupport": True,
                    },
                    "definition": {"dynamicRegistration": True, "linkSupport": True},
                    "references": {"dynamicRegistration": True},
                    "documentHighlight": {"dynamicRegistration": True},
                    "documentSymbol": {
                        "dynamicRegistration": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                        "hierarchicalDocumentSymbolSupport": True,
                        "tagSupport": {"valueSet": [1]},
                        "labelSupport": True,
                    },
                    "codeAction": {
                        "dynamicRegistration": True,
                        "isPreferredSupport": True,
                        "disabledSupport": True,
                        "dataSupport": True,
                        "resolveSupport": {"properties": ["edit"]},
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    "",
                                    "quickfix",
                                    "refactor",
                                    "refactor.extract",
                                    "refactor.inline",
                                    "refactor.rewrite",
                                    "source",
                                    "source.organizeImports",
                                ]
                            }
                        },
                        "honorsChangeAnnotations": False,
                    },
                    "codeLens": {"dynamicRegistration": True},
                    "formatting": {"dynamicRegistration": True},
                    "rangeFormatting": {"dynamicRegistration": True},
                    "onTypeFormatting": {"dynamicRegistration": True},
                    "rename": {
                        "dynamicRegistration": True,
                        "prepareSupport": True,
                        "prepareSupportDefaultBehavior": 1,
                        "honorsChangeAnnotations": True,
                    },
                    "documentLink": {"dynamicRegistration": True, "tooltipSupport": True},
                    "typeDefinition": {"dynamicRegistration": True, "linkSupport": True},
                    "implementation": {"dynamicRegistration": True, "linkSupport": True},
                    "colorProvider": {"dynamicRegistration": True},
                    "foldingRange": {
                        "dynamicRegistration": True,
                        "rangeLimit": 5000,
                        "lineFoldingOnly": True,
                        "foldingRangeKind": {"valueSet": ["comment", "imports", "region"]},
                        "foldingRange": {"collapsedText": False},
                    },
                    "declaration": {"dynamicRegistration": True, "linkSupport": True},
                    "selectionRange": {"dynamicRegistration": True},
                    "callHierarchy": {"dynamicRegistration": True},
                    "semanticTokens": {
                        "dynamicRegistration": True,
                        "tokenTypes": [
                            "namespace",
                            "type",
                            "class",
                            "enum",
                            "interface",
                            "struct",
                            "typeParameter",
                            "parameter",
                            "variable",
                            "property",
                            "enumMember",
                            "event",
                            "function",
                            "method",
                            "macro",
                            "keyword",
                            "modifier",
                            "comment",
                            "string",
                            "number",
                            "regexp",
                            "operator",
                            "decorator",
                        ],
                        "tokenModifiers": [
                            "declaration",
                            "definition",
                            "readonly",
                            "static",
                            "deprecated",
                            "abstract",
                            "async",
                            "modification",
                            "documentation",
                            "defaultLibrary",
                        ],
                        "formats": ["relative"],
                        "requests": {"range": True, "full": {"delta": True}},
                        "multilineTokenSupport": False,
                        "overlappingTokenSupport": False,
                        "serverCancelSupport": True,
                        "augmentsSyntaxTokens": True,
                    },
                    "linkedEditingRange": {"dynamicRegistration": True},
                    "typeHierarchy": {"dynamicRegistration": True},
                    "inlineValue": {"dynamicRegistration": True},
                    "inlayHint": {
                        "dynamicRegistration": True,
                        "resolveSupport": {"properties": ["tooltip", "textEdits", "label.tooltip", "label.location", "label.command"]},
                    },
                    "diagnostic": {"dynamicRegistration": True, "relatedDocumentSupport": False},
                },
                "window": {
                    "showMessage": {"messageActionItem": {"additionalPropertiesSupport": True}},
                    "showDocument": {"support": True},
                    "workDoneProgress": True,
                },
                "general": {
                    "staleRequestSupport": {
                        "cancel": True,
                        "retryOnContentModified": [
                            "textDocument/semanticTokens/full",
                            "textDocument/semanticTokens/range",
                            "textDocument/semanticTokens/full/delta",
                        ],
                    },
                    "regularExpressions": {"engine": "ECMAScript", "version": "ES2020"},
                    "markdown": {"parser": "marked", "version": "1.1.0"},
                    "positionEncodings": ["utf-16"],
                },
                "notebookDocument": {"synchronization": {"dynamicRegistration": True, "executionSummarySupport": True}},
            },
            "initializationOptions": {
                "isHttpEnabled": False,
                "compilerOptions": {
                    "snippetAutoIndent": False,
                },
                "decorationProvider": True,
                "didFocusProvider": True,
                "executeClientCommandProvider": True,
                "inputBoxProvider": True,
                "quickPickProvider": True,
                "slowTaskProvider": True,
                "treeViewProvider": True,
                "debuggingProvider": True,
                "disableColorOutput": True,
                "statusBarProvider": "log-message",
                "openFilesOnRenameProvider": True,
                "icons": "vscode",
                "openNewWindowProvider": False,
            },
            "trace": "verbose",
            "processId": os.getpid(),
            "workspaceFolders": [
                {
                    "uri": root_uri,
                    "name": os.path.basename(repository_absolute_path),
                }
            ],
        }
        return initialize_params

    @override
    def _start_server(self):
        """
        Starts the Metals Language Server
        """

        def execute_client_command_handler(params):
            return []

        def do_nothing(params):
            return

        def window_log_message(msg):
            self.logger.log(f"LSP: window/logMessage: {msg}", logging.INFO)

        def show_message_request(params):
            # Handle build import request - automatically accept
            if "message" in params and "Import build" in params.get("message", ""):
                return {"title": "Import build"}
            return None

        self.server.on_request("client/registerCapability", do_nothing)
        self.server.on_notification("metals/status", do_nothing)
        self.server.on_notification("window/logMessage", window_log_message)
        self.server.on_request("workspace/executeClientCommand", execute_client_command_handler)
        self.server.on_notification("$/progress", do_nothing)
        self.server.on_notification("textDocument/publishDiagnostics", do_nothing)
        self.server.on_request("window/showMessageRequest", show_message_request)
        self.server.on_notification("metals/executeClientCommand", do_nothing)
        self.server.on_notification("metals/bspStatus", do_nothing)
        self.server.on_notification("metals/treeViewDidChange", do_nothing)

        self.logger.log("Starting Metals server process", logging.INFO)
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        self.logger.log(
            "Sending initialize request from LSP client to LSP server and awaiting response",
            logging.INFO,
        )
        init_response = self.server.send.initialize(initialize_params)

        capabilities = init_response["capabilities"]
        assert "textDocumentSync" in capabilities, "Server must support textDocumentSync"
        assert "hoverProvider" in capabilities, "Server must support hover"
        assert "completionProvider" in capabilities, "Server must support code completion"
        assert "signatureHelpProvider" in capabilities, "Server must support signature help"
        assert "definitionProvider" in capabilities, "Server must support go to definition"
        assert "referencesProvider" in capabilities, "Server must support find references"
        assert "documentSymbolProvider" in capabilities, "Server must support document symbols"
        assert "workspaceSymbolProvider" in capabilities, "Server must support workspace symbols"

        self.server.notify.initialized({})
        self.completions_available.set()
