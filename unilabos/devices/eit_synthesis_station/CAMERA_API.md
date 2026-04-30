# Camera API

The existing `ops_http` service exposes camera snapshots and MJPEG streams on
the same `4670` port as the operations API.

## Configure

Copy `camera_env.example.bat` to `camera_env.bat` and fill the real password:

```bat
set CAM_USER=admin
set CAM_PASS=replace_me
set CAM_HOST=192.168.1.1
set CAM_PORT=554
set CAM_PYTHON=C:\ProgramData\Anaconda3\python.exe
```

`camera_env.bat` is ignored by git. Restart `ops_http` after changing it.

## Endpoints

```text
GET /api/cameras
GET /api/cameras/{camera_id}/status?stream=sub
GET /api/cameras/{camera_id}/snapshot.jpg?stream=sub
GET /api/cameras/{camera_id}/stream.mjpg?stream=sub
```

Valid camera IDs are `cam1`, `cam2`, and `cam3`. Valid streams are `sub` and
`main`; `sub` is the default.

Examples:

```powershell
curl http://127.0.0.1:4670/api/cameras
curl -o cam1.jpg "http://127.0.0.1:4670/api/cameras/cam1/snapshot.jpg?stream=sub"
```

From another host on the LAN:

```text
http://10.40.13.51:4670/api/cameras
http://10.40.13.51:4670/api/cameras/cam1/snapshot.jpg?stream=sub
```
