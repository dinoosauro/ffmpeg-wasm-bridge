import os
from pathlib import Path
import sys
from aiohttp import WSMsgType, web
import asyncio
import json
import secrets
import urllib.request
import socket
from importlib import resources

def get_cache_dir():
    """Get platform-appropriate cache directory"""
    if os.name == 'nt':  # Windows
        cache_dir = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:  # Unix-like
        cache_dir = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    
    return cache_dir / 'ffmpeg-wasm-bridge'

class FFmpegException(Exception):
    """
    An error occurred during the FFmpeg conversion.
    """
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class WebFetchException(Exception):
    """
    An error occurred while reading a resource from the user's device.
    """
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class FFmpegDeleteFileException(Exception):
    """
    An error occurred while deleting a file on FFmpeg WebAssembly's memfs.
    """
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class FileBridge:
    """
    The class that contains all the information of the files to read by FFmpeg WebAssembly.
    """
    def __init__(self, path: str, appears_in_commands_as: str = None, force_loading_name: str = None):
        """
        Create a FileBridge object
        Arguments:
            path: The path on the user's device of the resource. Should be a valid path, otherwise a WebFetchException will be thrown
            appears_in_commands_as: **Optional:** if the path appears in a different way in the command (for exampe, it's a relative path from somewhere else), use this field to write how in the command this file appears.
            force_loading_name: **Optional:** if this value is passed, the FFmpegOperation instance will fetch the file and add it in memory with this name, even if it's not mentioned in the command. A possible usage of this command is if you need to merge files (and so you need to provide a file list as a txt value, and then load all the videos/audios in the memory). **Note:** the webpage won't automatically delete from FFmpeg WebAssembly these files, so you should manually do it by calling the `delete_files` function.
        """
        self.path = path
        self.appears_in_commands_as = appears_in_commands_as
        self.force_loading_name = force_loading_name

class FFmpegServer:
    _show_ffmpeg_logging = True
    """
    When FFmpeg prints a message to the console, show it
    """
    _show_init_message = True
    """
    Show the welcome message
    """
    _throw_exceptions_if_failed = True
    """
    If an operation fails, throw an Exception to the Future
    """
    _connected_ws = None
    """
    The WebSocket object 
    """
    _current_operations: dict[str, dict[str, str]] = dict()
    """
    A nested dictionary: the main dictionary has as a key the ID of the FFmpegOperation, and returns a dictionary where the key is a Future ID, and the value its Future.
    This object is used to "resolve" these "promises" after a callback from the webpage has been triggered.
    """
    _ffmpeg_wasm_version = "0.11.x"
    """
    The version of FFmpeg WebAssembly that is being used.
    """
    async def _serve_file(self, filename: str, enforce_local_files=False):
        """Serve individual files
        Arguments:
            filename: the path of the file to get
            enforce_local_files: if true, the server will return the file only if its path is on the `_allowed_files` list.
        """
        print(filename)
        if (enforce_local_files and not filename in self._allowed_files) or not os.path.isfile(filename):
            raise web.HTTPNotFound()
        
        return web.FileResponse(
            path=filename,
            headers={
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Embedder-Policy": "require-corp"
            }
        )


    async def _serve_file_wrapper(self, request):
        """
        Serve a file from the user's device
        """
        return await self._serve_file(request.query.get("file"), True)

    async def _serve_ffmpeg_wrapper(self, request):
        """
        Server FFmpeg WebAssembly libraries
        """
        return await self._serve_file(f"{get_cache_dir()}{os.path.sep}{self._ffmpeg_wasm_version}{request.match_info.get('filename', '')}")
    
    async def _serve_index(self, request):
        """
        Serve the start page
        """
        return await self._serve_file(Path(__file__).parent / 'static' / 'index.html')

    async def _server_save(self, request):
        """
        Save the result to the user's device
        """
        file_name = request.query.get("filename", None)
        if file_name == None: return web.HTTPNotFound()
        id = request.query.get("id", None)
        if id == None or not id in self._current_operations: return web.HTTPUnauthorized()
        # Open the file and save it
        with open(file_name, 'wb') as file:
            async for chunk in request.content.iter_chunked(8192): 
                file.write(chunk)
            if (f"output_{file_name}" in self._current_operations[id]):
                self._current_operations[id][f"output_{file_name}"].set_result(None)
        return web.json_response({
            'status': 'success',
        })
        
    async def _get_websocket(self, request):
        """
        Open a WebSocket to establish bidirectional comunication between the server and the webpage
        """
        self._connected_ws = web.WebSocketResponse()
        await self._connected_ws.prepare(request)
        async for msg in self._connected_ws:
            if msg.type == WSMsgType.TEXT:
                json_msg = json.loads(msg.data)
                if ((json_msg.get("id", None) == None or not json_msg["id"] in self._current_operations) and json_msg["action"] != "serverReady"): continue # We'll enforce ID passing for every message, obviously except the "serverReady" action since it's called before any FFmpegOperation can be created.
                match(json_msg["action"]):
                    case "serverReady": # Webpage connected to the WebSocket
                        self._connected_to_ws.set_result(None)
                    case "log": # Logging received from FFmpeg
                        if self._show_ffmpeg_logging and "text" in json_msg: print(json_msg["text"])
                    # The following four actions follow the same syntax: something has gone wrong (or right), and so we need to trigger an exception in the first case (if the user wants so), and to "resolve" the Future in the second case.
                    # TODO: abstracting this in another function might be a great idea instead of this ugly copy-and-paste
                    case "failedConversion": # FFmpeg operation failed
                        if (json_msg["fileName"] in self._current_operations[json_msg["id"]]):
                            if self._throw_exceptions_if_failed: 
                                self._current_operations[json_msg["id"]][json_msg["fileName"]].set_exception(FFmpegException(json_msg["text"])) 
                            else: self._current_operations[json_msg["id"]][json_msg["fileName"]].set_result(None)
                    case "resourceFetched" | "failedResourceFetched": # Successful/Failed getting the resource from the user's drive
                        if f'fileload_{json_msg["url"]}' in self._current_operations[json_msg["id"]]:
                            if json_msg["action"] == "failedResourceFetched" and self._throw_exceptions_if_failed: 
                                self._current_operations[json_msg["id"]][f'fileload_{json_msg["url"]}'].set_exception(WebFetchException(json_msg["text"])) 
                            else: self._current_operations[json_msg["id"]][f'fileload_{json_msg["url"]}'].set_result(None)
                    case "fileRemoved" | "failedFileRemove": # Successful/Failed deleting some files
                        if f'delete_{json_msg["name"]}' in self._current_operations[json_msg["id"]]:
                            if json_msg["action"] == "failedFileRemove" and self._throw_exceptions_if_failed: 
                                self._current_operations[json_msg["id"]][f'delete_{json_msg["name"]}'].set_exception(FFmpegDeleteFileException(f'Failed removal of {json_msg["name"]}'))
                            else:
                                self._current_operations[json_msg["id"]][f'delete_{json_msg["name"]}'].set_result(None)
                    case "reloaded" | "failedReload": # Successful/Failed reloading FFmpeg
                        if "reload" in self._current_operations[json_msg["id"]]:
                            if json_msg["action"] == "failedReload" and self._throw_exceptions_if_failed: 
                                self._current_operations[json_msg["id"]][f"reload"].set_exception(FFmpegDeleteFileException("Failed FFmpeg reload"))
                            else:
                                self._current_operations[json_msg["id"]][f"reload"].set_result(None)
                    case "createFFmpeg": # The webpage's FFmpeg object was created
                        if "createffmpeg" in self._current_operations[json_msg["id"]]:
                            self._current_operations[json_msg["id"]]["createffmpeg"].set_result(None)



        return self._connected_ws
    _allowed_files: list[str] = []
    """
    The list of the allowed file paths that can be read from the server
    """
    def __init__(self, host="127.0.0.1", suggested_port = 10000):
        self.host = host
        """
        The host IP used for the server
        """
        self.port = suggested_port
        """
        The port of the server where the script will run
        """
        self._connected_to_ws = asyncio.Future()
        """
        A Future that'll be resolved when the connection to the WebSocket by the client has been established
        """
        self._started = asyncio.Future()
        """
        A Future that'll be resolved when the Server will be staretd
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Download the necessary resources for FFmpeg
        if not os.path.exists(get_cache_dir()): os.mkdir(get_cache_dir())

        for filename, url in dict({
            f"{self._ffmpeg_wasm_version}ffmpeg.min.js": "https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.11.6/dist/ffmpeg.min.js",
            f"{self._ffmpeg_wasm_version}ffmpeg-core.js": "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.11.0/dist/ffmpeg-core.js",
            f"{self._ffmpeg_wasm_version}ffmpeg-core.wasm": "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.11.0/dist/ffmpeg-core.wasm",
            f"{self._ffmpeg_wasm_version}ffmpeg-core.worker.js": "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.11.0/dist/ffmpeg-core.worker.js",
        }).items():
            if not os.path.isfile(f"{get_cache_dir()}{os.path.sep}{filename}"):
                print(f"Downloading FFmpeg WebAssembly ({filename})")
                urllib.request.urlretrieve(url, f"{get_cache_dir()}{os.path.sep}{filename}")

    def _check_port(self, host: str = None, port: int = None):
        """
        Check if a port is available. Returns the first available port, starting from the `port` value.
        Arguments:
            host: the hostname that should be checked. If nothing is provided, the `self` host will be used
            port: the first port the function will look if available. If nothing is provided, the `self` port will be used.
        """
        if (port == None): port = self.port
        if (host == None): host = self.host
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port)) # Port available
                return port
            except OSError:
                return self._check_port(host, port + 1)


    async def start(self):
        if hasattr(self, '_runner') and self._runner is not None: # Avoid running the server multiple times
            print("Server is already running!")
            return
        app = web.Application()
        app.router.add_get('/ffmpeg/{filename}', self._serve_ffmpeg_wrapper) # Get FFmpeg code
        app.router.add_get('/files/', self._serve_file_wrapper) # Get user's local files 
        app.router.add_get('/', self._serve_index) # Get the index.html page
        app.router.add_get('/ws/{id}', self._get_websocket) # Connect to the WebSocket
        app.router.add_post('/save/', self._server_save)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._actual_port = self._check_port()
        """
        The port where the server has started. This is the first available port from `self.port`
        """
        self.site = web.TCPSite(self._runner, host=self.host, port=self._actual_port)
        await self.site.start()
        if self._show_init_message:
            print(f"Server started! To convert your files, go to http://{self.host}:{self._actual_port}/")
        self._started.set_result(None)

class FFmpegOperation:
    """
    Create a new operation with FFmpeg.
    This class permits to run commands with FFmpeg and handle its file system.
    Every FFmpegOperation has its own file system.
    """
    _source_ready = False
    """
    If true, the webpage is ready to convert files, since the FFmpeg object with this ID has been established.
    """
    def __init__(self, source: FFmpegServer):
        self.server = source
        """
        The server object to which this FFmpegOperation is tied
        """
        self.id = secrets.token_hex(32)
        """
        The ID of the current FFmpeg operation
        """

    async def create_ffmpeg(self): 
        """
        Create the FFmpeg object of this operation to the 
        """
        if self._source_ready: return
        await self.server._connected_to_ws
        promise = asyncio.Future()
        self.server._current_operations[self.id] = dict() # Create the new dictionary that'll contain all the Futures of this operation
        self.server._current_operations[self.id]["createffmpeg"] = promise
        await self.server._connected_ws.send_json({
            "action": "createFFmpeg",
            "id": self.id
        })
        await promise
        self._source_ready = True
    async def run(self, commands: list[str], files: list[FileBridge] = []):
        """
        Run a script on this FFmpeg operation.
        You can run scripts of multiple operations at the same time, but inside the operation you need to wait that the current command finishes before launching a new one.
        Arguments:
            commands: an array of the arguments to pass to FFmpeg
            files: a list of FileBridge objects that should be loaded in FFmpeg. If no list is provided, the function will try to get the files to fetch automatically.
        """
        await self.create_ffmpeg()
        if len(files) == 0: # Since no files have been specified, we'll need to fetch ourselves. We currently look to the "-i" command to get which files should be added
            for i in range(0, len(commands)):
                if commands[i] == "-i":
                    file_name = commands[i+1]
                    if not os.path.isfile(file_name): file_name = f"{os.getcwd()}{os.path.sep}{file_name}" # Fallback for relative paths
                    files.append(FileBridge(path=file_name, appears_in_commands_as=commands[i+1]))
        for file in files: # Make sure every file can be fetched by the script
            if file.appears_in_commands_as == None: file.appears_in_commands_as = file.path
            if (file.appears_in_commands_as in commands):
                commands[commands.index(file.appears_in_commands_as)] =  f"http/files/?file={file.path}"
                self.server._allowed_files.append(file.path)
            elif file.force_loading_name != None: # In this case, we need to force load the file. So, we'll ask the webpage script to load it, and we'll wait until it has been fetched.
                self.server._allowed_files.append(file.path)
                url = f"http/files/?file={file.path}"
                await self.server._connected_ws.send_json({
                    "action": "addFile",
                    "url": url,
                    "name": file.force_loading_name,
                    "id": self.id
                })  
                promise = asyncio.Future()
                self.server._current_operations[self.id][f"fileload_{url}"] = promise
                await promise
        
        # Now, let's send the request to the webpage to start the FFmpeg command
        promise = asyncio.Future()
        self.server._current_operations[self.id][f"output_{commands[len(commands) - 1]}"] = promise
        await self.server._connected_ws.send_json({
            "action": "start",
            "command": commands,
            "id": self.id
        })
        await promise

    async def delete_files(self, files: list[FileBridge]):
        """
        Delete some files from FFmpeg WebAssembly's memory. You should call this only for the files you've loaded by specifying the `force_loading_name` parameter in the FileBridge class, since cleaning of the other files is done automatically by the script. Note that this has no effect on the user's drive, but only on the virtual file system used by FFmpeg WebAssembly. 
        Arguments:
            files: a list of the files to delete. These object must have the `force_loading_name` string, otherwise the function will skip them.
        """
        await self.create_ffmpeg()
        for file in files:
            if file.force_loading_name == None: continue
            promise = asyncio.Future()
            self.server._current_operations[self.id][f"delete_{file.force_loading_name}"] = promise
            await self.server._connected_ws.send_json({
                "action": "removeFile",
                "name": file.force_loading_name,
                "id": self.id
            })
            await promise

    async def reload_ffmpeg(self):
        """
        Exit and reload the current FFmpeg operation.
        This should help reducing RAM usage.
        """
        await self.create_ffmpeg()
        promise = asyncio.Future()
        self.server._current_operations[self.id]["reload"] = promise
        await self.server._connected_ws.send_json({
            "action": "reload",
            "id": self.id
        })
        await promise


async def _fallback():
    """
    This function is ran only if the user calls the server.py Python script from the command line.
    It uses all the arguments from the command line to build the FFmpeg command. 
    The script automatically fetches the requested files.
    """
    server = FFmpegServer()
    await asyncio.create_task(server.start())
    await FFmpegOperation(server).run(commands=sys.argv[1:], files=[])

def _main():
    """
    Synchronous wrapper for the async _fallback function
    """
    asyncio.run(_fallback())

if __name__ == "__main__":
    _main()