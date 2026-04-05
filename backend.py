import os
import json
import base64
import uuid
import folder_paths
from aiohttp import web, WSMsgType
from server import PromptServer

# Directories setup
extension_path = os.path.dirname(os.path.abspath(__file__))
ps_inputs_directory = os.path.join(extension_path, "data", "ps_inputs")

# Create data directory if it doesn't exist
os.makedirs(ps_inputs_directory, exist_ok=True)

clients = {}
photoshop_users = []
comfyui_users = []

async def save_file(data_b64, filename):
    data = base64.b64decode(data_b64)
    file_path = os.path.join(ps_inputs_directory, filename)
    with open(file_path, "wb") as f:
        f.write(data)

async def send_message(user_list, msg_type, message=True):
    try:
        if not user_list:
            print(f"[PromptFix] Target platform users not connected")
            return
        
        # Send to all connected users of this platform
        for user_id in list(user_list):
            if user_id in clients:
                ws = clients[user_id]["ws"]
                data = json.dumps({msg_type: message}) if msg_type else message
                await ws.send_str(data)
    except Exception as e:
        print(f"[PromptFix] Error sending message: {e}")

@PromptServer.instance.routes.get("/promptfix/ws")
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    client_id = request.query.get("clientId", str(uuid.uuid4()))
    platform = request.query.get("platform", "unknown")
    clients[client_id] = {"ws": ws, "platform": platform}

    print(f"[PromptFix] Connected client {client_id} on platform {platform}")

    if platform == "ps":
        photoshop_users.append(client_id)
        if comfyui_users:
            await send_message(comfyui_users, "photoshopConnected", True)
    elif platform == "cm":
        comfyui_users.append(client_id)
        if photoshop_users:
            await send_message(comfyui_users, "photoshopConnected", True)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await handle_message(client_id, platform, msg.data)
            elif msg.type == WSMsgType.ERROR:
                print(f"[PromptFix] WebSocket error from {client_id}: {ws.exception()}")
    except Exception as e:
        pass
    finally:
        await handle_disconnect(client_id, platform)

    return ws

async def handle_message(client_id, platform, data):
    try:
        msg = json.loads(data)
    except json.JSONDecodeError:
        print(f"[PromptFix] Invalid JSON from {client_id}")
        return

    # From ComfyUI Browser to Photoshop
    if platform == "cm":
        try:
            # Relay anything else back to Photoshop plugin
            await send_message(photoshop_users, "", json.dumps(msg))
        except Exception as e:
            print(f"[PromptFix] Error relaying from ComfyUI: {e}")

    # From Photoshop to ComfyUI Browser
    elif platform == "ps":
        try:
            if "canvasBase64" in msg:
                await save_file(msg["canvasBase64"], "PS_canvas.png")
            if "maskBase64" in msg:
                await save_file(msg["maskBase64"], "PS_mask.png")
            
            # Request translation to queue
            if msg.get("queue"):
                print("[PromptFix] Triggering 'Queue Prompt' to ComfyUI UI")
                await send_message(comfyui_users, "queue", True)
                
        except Exception as e:
            print(f"[PromptFix] Error handling message from PS: {e}")

async def handle_disconnect(client_id, platform):
    if client_id in clients:
        del clients[client_id]
        
    if platform == "ps" and client_id in photoshop_users:
        photoshop_users.remove(client_id)
        print(f"[PromptFix] Photoshop disconnected {client_id}")
    elif platform == "cm" and client_id in comfyui_users:
        comfyui_users.remove(client_id)
        print(f"[PromptFix] ComfyUI disconnected {client_id}")

@PromptServer.instance.routes.get("/promptfix/renderdone")
async def handle_render_done(request):
    try:
        filename = request.rel_url.query.get("filename")
        if not filename:
            return web.Response(status=400, text="Filename required")
            
        filepath = os.path.join(folder_paths.get_temp_directory(), filename)
        
        with open(filepath, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        
        print(f"[PromptFix] Sending render result back to Photoshop (Size: {len(encoded_string)})")
        await send_message(photoshop_users, "render", encoded_string)
        return web.Response(text="Success")
    except Exception as e:
        print(f"[PromptFix] Error returning render to PS: {e}")
        return web.Response(status=500, text=str(e))
