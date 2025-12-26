from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import os

# ---------------------------------------------------------
# 1. MCP 도구 및 로직 정의
# ---------------------------------------------------------
mcp = FastMCP("BusRam")

# 키 설정
ENCODING_KEY = "ezGwhdiNnVtd%2BHvkfiKgr%2FZ4r%2BgvfeUIRz%2FdVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI%2B%2FpJFoYr9Ce%2BTDg%3D%3D"
DECODING_KEY = urllib.parse.unquote(ENCODING_KEY)

@mcp.tool(description="정류장 이름을 검색해서 ID와 ARS 번호를 찾습니다. 사용자가 '강남역' 등을 물어볼 때 사용합니다.")
def search_station(keyword: str) -> str:
    """[1단계] 정류장 이름을 검색해서 ID를 찾습니다."""
    base_url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
    url = f"{base_url}?serviceKey={ENCODING_KEY}&cityCode=11&nodeNm={keyword}&numOfRows=5&_type=json"
    try:
        response = requests.get(url, timeout=10)
        try: data = response.json()
        except: return f"공공데이터 오류: {response.text}"
        
        if 'response' not in data: return f"API 에러: {data}"
        if data['response']['header']['resultCode'] != '00': return "공공데이터 에러"
        if data['response']['body']['totalCount'] == 0: return "검색 결과 없음"
        
        items = data['response']['body']['items']['item']
        if isinstance(items, dict): items = [items]
        
        result = f"🔍 '{keyword}' 검색 결과:\n"
        for item in items:
            name = item.get('nodeNm')
            node_id = item.get('nodeid') 
            ars_id = item.get('nodeno')
            result += f"- {name} (ID: {node_id}) / 정류장번호: {ars_id}\n"
        return result
    except Exception as e: return f"에러: {str(e)}"

@mcp.tool(description="특정 정류장의 버스 도착 정보를 실시간으로 조회합니다. 몇 분 남았는지 알려줍니다.")
def check_arrival(city_code: str, station_id: str) -> str:
    """[2단계] 도착 정보 조회"""
    base_url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"
    url = f"{base_url}?serviceKey={ENCODING_KEY}&cityCode={city_code}&nodeId={station_id}&numOfRows=10&_type=json"
    try:
        response = requests.get(url, timeout=10)
        try: data = response.json()
        except: return f"공공데이터 오류: {response.text}"
        
        if 'response' not in data: return f"API 에러: {data}"
        if data['response']['header']['resultCode'] != '00': return "공공데이터 에러"
        if data['response']['body']['totalCount'] == 0: return "도착 예정 버스 없음"
        
        items = data['response']['body']['items']['item']
        if isinstance(items, dict): items = [items]
        
        result = f"정류장(ID:{station_id}) 도착 정보:\n"
        for item in items:
            bus = item.get('routeno') 
            left_stat = item.get('arrprevstationcnt') 
            min_left = int(item.get('arrtime')) // 60
            result += f"- [{bus}번] {min_left}분 후 도착 ({left_stat}정거장 전)\n"
        return result
    except Exception as e: return f"에러: {str(e)}"

# ---------------------------------------------------------
# 2. Starlette 서버 설정 (Render 배포용)
# ---------------------------------------------------------
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

# FastMCP 내부 서버 객체
mcp_server = mcp._mcp_server
sse = SseServerTransport("/mcp") # 경로는 /mcp 로 통일

async def handle_sse_connect(request):
    """[GET] 연결"""
    print("[GET /mcp] 연결 시도")
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())

async def handle_sse_message(request):
    """[POST] 메시지"""
    # PlayMCP Health Check 대응 (Session ID 없음 방어)
    if "session_id" not in request.query_params:
        print("[PlayMCP] Health Check (200 OK 응답)")
        return JSONResponse({"status": "healthy"}, status_code=200)

    try:
        await sse.handle_post_message(request.scope, request.receive, request._send)
    except Exception as e:
        print(f"Error handling message: {e}")

async def handle_root(request):
    """[GET] 루트"""
    return JSONResponse({"status": "ok", "service": "BusRam MCP"})

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

# 👇 [중요] app 객체를 전역 변수로 만듭니다. (Uvicorn이 이걸 찾아서 실행함)
app = Starlette(
    debug=True,
    routes=[
        Route("/mcp", endpoint=handle_sse_connect, methods=["GET"]),
        Route("/mcp", endpoint=handle_sse_message, methods=["POST"]),
        Route("/", endpoint=handle_root, methods=["GET"])
    ],
    middleware=middleware
)