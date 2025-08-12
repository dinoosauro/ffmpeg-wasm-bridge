# ffmpeg-wasm-bridge

A simple Python server that allows to convert files totally on device using
FFmpeg WebAssembly.

Install it from PyPI and use it [both from the command line](#from-the-command-line) and [in your Python projects](#in-another-python-script): `pip install ffmpeg-wasm-bridge`

## How it works

This script creates a local server (usually, on `http://localhost:10000`, but
can be customized). The user will have to open the webpage, and then the script
will handle everything else: the files will be loaded in FFmpeg WebAssembly, the
command will be executed and the file will be saved on the user's local drive.

## Usage

### From the command line

From the command line, pass all the FFmpeg arguments (excluding `ffmpeg` at the
start) in the Python `server.py` file. Connect to the webpage the script will
print in the console, and the script will handle everything else.

Example: `python3 server.py -i file_0.mp3 -acodec libopus file_0.ogg`

### In another Python script

You can use this server in your Python scripts/applications using the two
exposed classes (`FFmpegServer` and `FFmpegOperation`). You can find a small
script example here below:

```
server = FFmpegServer()
await asyncio.create_task(server.start())
operation = FFmpegOperation(server)
await operation.run(commands=["-i", "file_0.mp3" "-acodec", "libopus", "file_0.ogg"])
```

To learn more about what each class does, and what are the function you should
run, see the `Classes` section below.

## Classes

There are three classes that can help you with implementing ffmpeg-wasm-bridge
in your application:

### FFmpegServer

The server that'll be used for this FFmpeg operation. _While you can do whatever
you want_, I would suggest you to create only a FFmpegServer per application,
since multiple servers are unnecessary (but they should still work!)

#### Parameters

You can specify two **optional** parameters to the FFmpegServer class:

| Parameter name | Description | Extra notes |
| - | - | - |
| `host`| The hostname for the new sever. | Defaults to `127.0.0.1` |
| `suggested_port` | the port that **should** be used for this server. | Defaults to `10000`.<br>**Note:** the script will always use the first available port from this value. So, for example, if port `10000` is being used elsewhere, the script will try using port `10001`, and so on. |

#### Functions

| Function name | Description | Parameters |
| - | - | - |
| `start` | Starts the FFmpeg server | None |

### FFmpegOperation

This class creates a new FFmpeg WebAssembly instance on the webpage. Each
instance has its own file system. While an instance can run only a FFmpeg
command at a time, you are free to create multiple FFmpegOperations to run
multiple commands.

#### Parameters

You need to specify only a parameter in the FFmpegOperation class, that is the
FFmpegServer this class will depend on.

#### Functions

| Function name | Description | Parameters |
| - | - | - |
`create_ffmpeg` | Creates a new FFmpeg WebAssembly object in the webpage. |  This should be called only one time, and will automatically be called when you use any other function of the FFmpegOperation class, so you can ignore it. |
| `run` | Runs the provided command. | <ul><li>`commands`: a list of strings with the FFmpeg command to execute (without `ffmpeg` at the start);</li><li>`files`: an **optional** FileBridge list. See below to understand what the FileBridge class does. If nothing is passed, the script will automatically try to understand which files should be loaded in FFmpeg WebAssembly.</li></ul>|
| `delete_files` | Deletes files that have been **manually loaded** in FFmpeg WebAssembly, so the ones where you have specified the `force_loading_name` property in the FileBridge object. All the other files will automatically be deleted after the conversion has been done. | This function has only an argument, that is the list of FileBridge objects to delete. |
| `reload_ffmpeg` | Reloads the FFmpeg object. | This could help reducing RAM usage from FFmpeg WebAssembly. |

### FileBridge

This class is used to specify that a file should be read by the webpage.

#### Parameters

| Parameter name | Description | Extra notes |
| - | - | - |
| `path` | A string with the file path on the user's device | - |
| `appears_in_command_str` | **Optional value.** If the path appears in a different way in the command (for exampe, it's a relative path from somewhere else), use this field to write how in the command this file appears | - |
| `force_loading_name` | **Optional value.** If this value is passed, the FFmpegOperation instance will fetch the file and add it in memory with this name, even if it's not mentioned in the command. | A possible usage of this command is if you need to merge files (and so you need to provide a file list as a txt value, and then load all the videos/audios in the memory). <br>**Note:** the webpage won't automatically delete from FFmpeg WebAssembly these files, so you should manually do it by calling the `delete_files` function.

## Licenses

This project is published under the MIT license.

The project uses the following open source libraries:

- `aiohttp`: library used to create the server [[MIT license]](https://github.com/aio-libs/aiohttp)
- `ffmpeg.wasm`: build of FFmpeg in WebAssembly [[MIT license]](https://github.com/ffmpegwasm/ffmpeg.wasm)

Note that the server will download the first time it's run the FFmpeg WebAssembly files from JSDelivr. After that time, you can use the server completely offline.