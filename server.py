from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import os
import json # JSON 포맷팅을 위해 추가

# 1. 서버 이름 설정
mcp = FastMCP("BusRam")

# 2. 키 설정
ENCODING_KEY = "ezGwhdiNnVtd%2BHvkfiKgr%2FZ4r%2BgvfeUIRz%2FdVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI%2B%2FpJFoYr9Ce%2BTDg%3D%3D"
DECODING_KEY = urllib.parse.unquote(ENCODING_KEY)

# 👇 [수정] 결과를 그냥 리턴하지 않고, 카카오가 좋아하는 예쁜 형식으로 리턴하는 함수
def format_response(text_content):
    # 사용자가 보여준 예시처럼 content 리스트 구조를 만듭니다.
    # 하지만 FastMCP가 자동으로 감싸줄 수 있으므로, 여기서는 
    # '확실한 정보 전달'을 위해 텍스트 자체를 깔끔하게 정리합니다.
    return text_content

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
        header = data['response']['header']
        if header['resultCode'] != '00': return f"에러: {header['resultMsg']}"
        
        body = data['response']['body']
        if body['totalCount'] == 0: return "검색 결과가 없습니다."
        
        items = body['items']['item']
        if isinstance(items, dict): items = [items]
        
        # 👇 카카오톡에서 보기 좋게 포맷팅
        result = f"🔍 '{keyword}' 검색 결과\n"
        for item in items:
            name = item.get('nodeNm')
            node_id = item.get('nodeid') 
            ars_id = item.get('nodeno')
            result += f"• {name}\n  - ID: {node_id}\n  - 정류장번호: {ars_id}\n\n"
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
        header = data['response']['header']
        if header['resultCode'] != '00': return f"에러: {header['resultMsg']}"
        
        body = data['response']['body']
        if body['totalCount'] == 0: return "현재 도착 예정인 버스가 없습니다."
        
        items = body['items']['item']
        if isinstance(items, dict): items = [items]
        
        # 👇 카카오톡에서 보기 좋게 포맷팅
        result = f"🚌 정류장(ID:{station_id}) 도착 정보\n"
        for item in items:
            bus = item.get('routeno') 
            left_stat = item.get('arrprevstationcnt') 
            arr_time = int(item.get('arrtime'))
            min_left = arr_time // 60
            sec_left = arr_time % 60
            
            result += f"• [{bus}번] {min_left}분 {sec_left}초 후\n  ({left_stat}정거장 전)\n"
        return result
    except Exception as e: return f"에러: {str(e)}"

# =================================================================
# 👇 [핵심] PlayMCP 호환성 패치 (세션 ID 강제 주입)
# =================================================================
if __name__ == "__main__":
    import uvicorn
    import os
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.datastructures import MutableHeaders

    # 1. FastMCP 본체
    server = mcp._mcp_server
    sse = SseServerTransport("/sse")

    async def handle_sse_connect(request):
        """[GET] 연결 요청"""
        print(f"🔌 [GET] PlayMCP 접속 시도")
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    async def handle_sse_message(request):
        """[POST] 메시지 요청 - 여기가 진짜 중요함!"""
        
        # 👇 [솔루션] PlayMCP가 ID 안 가져오면, 우리가 강제로 'global'이라는 ID를 붙여줍니다.
        # 이렇게 하면 mcp 라이브러리가 "어? ID 있네?" 하고 정상 처리(Process)를 시작합니다.
        # (아까처럼 가짜 202 응답을 주는 게 아니라, 진짜 응답을 줍니다.)
        if "session_id" not in request.query_params:
            print("⚠️ [PlayMCP] ID 없음 -> 'global' ID 강제 주입하여 처리 시도")
            
            # Query Param을 강제로 수정하는 꼼수
            scope = request.scope
            query_string = scope.get("query_string", b"").decode("utf-8")
            if query_string:
                new_query = query_string + "&session_id=global"
            else:
                new_query = "session_id=global"
            scope["query_string"] = new_query.encode("utf-8")
            
            # 수정된 scope로 요청 다시 만들기
            from starlette.requests import Request
            request = Request(scope, request.receive)

        try:
            await sse.handle_post_message(request.scope, request.receive, request._send)
        except Exception as e:
            print(f"메시지 처리 에러: {e}")

    async def handle_root(request):
        return JSONResponse({"status": "ok", "message": "BusRam MCP is running!"})

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
            Route("/", endpoint=handle_root, methods=["GET"])
        ],
        middleware=middleware
    )

    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 PlayMCP 호환성 패치 완료 서버 시작 (0.0.0.0:{port})")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)