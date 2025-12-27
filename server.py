from mcp.server.fastmcp import FastMCP
import requests
import os
import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse, Response
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from urllib.parse import unquote

# 1. 서버 설정
mcp = FastMCP("BusRam")

# [중요] 키 관리: Decoding Key를 입력받거나, Encoding Key라면 디코딩해서 사용

RAW_KEY = "ezGwhdiNnVtd+HvkfiKgr/Z4r+gvfeUIRz/dVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI+/pJFoYr9Ce+TDg=="
# 만약 키가 %2B 등으로 시작한다면 아래 코드가 자동으로 디코딩해서 처리합니다.
SERVICE_KEY = unquote(RAW_KEY) 

@mcp.tool(description="정류장 이름을 검색해서 ID와 ARS 번호를 찾습니다. city_code는 서울:11, 경기도:12 등입니다.")
def search_station(keyword: str, city_code: str = "11") -> str:
    print(f"[Tool] 정류장 검색 시작: {keyword} (도시: {city_code})")
    
    # 주의: 이 API(BusSttnInfoInqireService)는 '버스도착정보'와 별도로 신청해야 할 수 있습니다.
    url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
    
    # serviceKey는 requests가 자동으로 인코딩하므로, 여기서는 디코딩된 순수 키를 줍니다.
    params = {
        "serviceKey": SERVICE_KEY, 
        "cityCode": city_code, 
        "nodeNm": keyword, 
        "numOfRows": 5, 
        "_type": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        # 응답 내용 디버깅용 출력
        print(f"[Debug] 응답 코드: {response.status_code}")
        
        try: 
            data = response.json()
        except: 
            return f"API 응답이 JSON이 아닙니다. API 키 오류일 수 있습니다.\n응답내용: {response.text[:200]}"
        
        if 'response' not in data: 
            return f"API 구조 에러: {data}"
            
        header = data['response'].get('header', {})
        if header.get('resultCode') != '00':
            return f"API 에러 발생 (Code: {header.get('resultCode')}): {header.get('resultMsg')}"

        if data['response']['body']['totalCount'] == 0: 
            return f"'{keyword}'에 대한 검색 결과가 없습니다."
        
        items = data['response']['body']['items']['item']
        if isinstance(items, dict): items = [items]
        
        result = f"'{keyword}' 검색 결과:\n"
        for item in items:
            result += f"- {item.get('nodeNm')} (ID: {item.get('nodeid')})\n"
        return result
    except Exception as e: 
        return f"시스템 에러: {str(e)}"

@mcp.tool(description="정류장 ID로 버스 도착 정보를 조회합니다.")
def check_arrival(city_code: str, station_id: str) -> str:
    print(f"[Tool] 도착 정보 조회: {station_id}")
    url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"
    
    params = {
        "serviceKey": SERVICE_KEY, 
        "cityCode": city_code, 
        "nodeId": station_id, 
        "numOfRows": 10, 
        "_type": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        try: data = response.json()
        except: return f"Error parsing JSON: {response.text}"
        
        if 'response' not in data: return f"API Error: {data}"
        
        header = data['response'].get('header', {})
        if header.get('resultCode') != '00':
             return f"API Key Error or Limit Exceeded: {header.get('resultMsg')}"

        if data['response']['body']['totalCount'] == 0: 
            return "현재 도착 예정인 버스가 없습니다."
        
        items = data['response']['body']['items']['item']
        if isinstance(items, dict): items = [items]
        
        result = f"정류장(ID:{station_id}) 도착 정보:\n"
        for item in items:
            arr_time = item.get('arrtime')
            min_left = int(arr_time) // 60 if arr_time else 0
            route_no = item.get('routeno')
            # 2분 미만은 '잠시 후'로 표시 등 사용자 친화적 가공
            msg = f"{min_left}분 후" if min_left > 1 else "잠시 후 도착"
            result += f"- [{route_no}번] {msg}\n"
        return result
    except Exception as e: return f"Error: {str(e)}"

# 3. Starlette 설정 (Kakao Play MCP 등록용)
server = mcp._mcp_server
sse = SseServerTransport("/mcp")

class AlreadyHandledResponse(Response):
    async def __call__(self, scope, receive, send): return

async def handle_sse_connect(request):
    print(f"[SSE] 연결 시도")
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())
    return AlreadyHandledResponse()

async def handle_sse_message(request):
    # Kakao Play MCP 등에서 헬스 체크용으로 호출할 수 있음
    if "session_id" not in request.query_params:
        print("[Check] Health Check Ping -> 200 OK")
        return JSONResponse({"status": "healthy"})

    try:
        await sse.handle_post_message(request.scope, request.receive, request._send)
    except Exception as e:
        print(f"Message Error: {e}")
    return AlreadyHandledResponse()

async def handle_root(request):
    return JSONResponse({"status": "Bus MCP Server is Running!"})

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"], # 중요: Kakao 서버에서의 접근 허용
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(
    debug=True,
    routes=[
        Route("/mcp", endpoint=handle_sse_connect, methods=["GET"]),
        Route("/mcp", endpoint=handle_sse_message, methods=["POST"]),
        Route("/", endpoint=handle_root, methods=["GET"])
    ],
    middleware=middleware
)