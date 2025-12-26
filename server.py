from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import os

# 1. 서버 이름 설정
mcp = FastMCP("BusAlert")

# 2. 키 설정
ENCODING_KEY = "ezGwhdiNnVtd%2BHvkfiKgr%2FZ4r%2BgvfeUIRz%2FdVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI%2B%2FpJFoYr9Ce%2BTDg%3D%3D"
DECODING_KEY = urllib.parse.unquote(ENCODING_KEY)

@mcp.tool()
def search_station(keyword: str) -> str:
    """[1단계] 정류장 이름을 검색해서 ID를 찾습니다."""
    base_url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
    # URL 직접 조립 (인코딩 문제 방지)
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

@mcp.tool()
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
        result = f"🚌 정류장(ID:{station_id}) 도착 정보:\n"
        for item in items:
            bus = item.get('routeno') 
            left_stat = item.get('arrprevstationcnt') 
            min_left = int(item.get('arrtime')) // 60
            result += f"- [{bus}번] {min_left}분 후 도착 ({left_stat}정거장 전)\n"
        return result
    except Exception as e: return f"에러: {str(e)}"

# =================================================================
# 👇 [최종 완결판] 모든 문을 다 열어두는 서버 코드
# =================================================================
if __name__ == "__main__":
    import uvicorn
    import os
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import Response, JSONResponse
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    # 1. FastMCP 본체 가져오기
    server = mcp._mcp_server
    sse = SseServerTransport("/sse")

    # Crash 방지용 특수 응답 클래스
    class AlreadyHandledResponse(Response):
        async def __call__(self, scope, receive, send):
            pass 

    async def handle_sse_connect(request):
        """[GET] /sse 연결"""
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return AlreadyHandledResponse()

    async def handle_sse_message(request):
        """[POST] /sse 대화"""
        try:
            await sse.handle_post_message(request.scope, request.receive, request._send)
        except Exception:
            pass
        return AlreadyHandledResponse()

    async def handle_root(request):
        """[GET] / 헬스 체크 (이게 없어서 PlayMCP가 404로 착각했을 수 있음)"""
        return JSONResponse({"status": "ok", "message": "BusRam MCP is running!"})

    # 2. 웹 서버 설정 (현관문, 뒷문 다 엶)
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse_connect, methods=["GET"]),
            Route("/sse", endpoint=handle_sse_message, methods=["POST"]),
            Route("/", endpoint=handle_root, methods=["GET"]) # 👈 현관문 추가!
        ],
        middleware=middleware
    )

    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 최종 서버 시작 (0.0.0.0:{port})")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)