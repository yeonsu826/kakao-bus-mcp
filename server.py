from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import os

# 1. 서버 이름 & 키
mcp = FastMCP("BusRam")
DECODING_KEY = "ezGwhdiNnVtd+HvkfiKgr/Z4r+gvfeUIRz/dVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI+/pJFoYr9Ce+TDg==" # 본인 키 입력 필수!


# 2. 도구 정의
@mcp.tool(description="정류장 이름을 검색해서 ID와 ARS 번호를 찾습니다.")
def search_station(keyword: str) -> str:
    print(f"[Tool] search_station: {keyword}")
    url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
    params = {"serviceKey": DECODING_KEY, "cityCode": "11", "nodeNm": keyword, "numOfRows": 5, "_type": "json"}
    try:
        response = requests.get(url, params=params, timeout=10)
        try: data = response.json()
        except: return f"Error: {response.text}"
        
        if 'response' not in data: return f"API Error: {data}"
        if data['response']['body']['totalCount'] == 0: return "검색 결과 없음"
        
        items = data['response']['body']['items']['item']
        if isinstance(items, dict): items = [items]
        
        result = f" '{keyword}' 검색 결과:\n"
        for item in items:
            result += f"- {item.get('nodeNm')} (ID: {item.get('nodeid')})\n"
        return result
    except Exception as e: return f"Error: {str(e)}"

@mcp.tool(description="특정 정류장의 버스 도착 정보를 실시간으로 조회합니다.")
def check_arrival(city_code: str, station_id: str) -> str:
    print(f"[Tool] check_arrival: {station_id}")
    url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"
    params = {"serviceKey": DECODING_KEY, "cityCode": city_code, "nodeId": station_id, "numOfRows": 10, "_type": "json"}
    try:
        response = requests.get(url, params=params, timeout=10)
        try: data = response.json()
        except: return f"Error: {response.text}"
        
        if 'response' not in data: return f"API Error: {data}"
        if data['response']['body']['totalCount'] == 0: return "도착 정보 없음"
        
        items = data['response']['body']['items']['item']
        if isinstance(items, dict): items = [items]
        
        result = f" 정류장(ID:{station_id}) 도착 정보:\n"
        for item in items:
            min_left = int(item.get('arrtime')) // 60
            result += f"- [{item.get('routeno')}번] {min_left}분 후\n"
        return result
    except Exception as e: return f"Error: {str(e)}"

# 3. Starlette 서버 설정 (여기가 중요!)
# =================================================================
import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse, Response
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

server = mcp._mcp_server
sse = SseServerTransport("/mcp") # 경로는 /mcp

# Crash 방지용 클래스
class AlreadyHandledResponse(Response):
    async def __call__(self, scope, receive, send):
        return

async def handle_sse_connect(request):
    print(f"[GET] 연결 시도")
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())
    return AlreadyHandledResponse()

async def handle_sse_message(request):
    # PlayMCP 체크 (ID 없음) -> 200 OK 반환 (중요!)
    if "session_id" not in request.query_params:
        print("[Health Check] ID 없음 -> 200 OK 반환")
        return JSONResponse({"status": "healthy"}, status_code=200)

    try:
        await sse.handle_post_message(request.scope, request.receive, request._send)
    except Exception as e:
        print(f"Message Error: {e}")
    
    return AlreadyHandledResponse()

async def handle_root(request):
    return JSONResponse({"status": "ok"})

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

# 👇 [핵심 수정] app 변수를 if문 밖으로 꺼냈습니다!
# 이제 Render가 'server:app'을 찾을 수 있습니다.
app = Starlette(
    debug=True,
    routes=[
        Route("/mcp", endpoint=handle_sse_connect, methods=["GET"]),
        Route("/mcp", endpoint=handle_sse_message, methods=["POST"]),
        Route("/", endpoint=handle_root, methods=["GET"])
    ],
    middleware=middleware
)

# 로컬 테스트용 (Render는 이 부분을 실행하지 않고 위의 app을 직접 가져갑니다)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)