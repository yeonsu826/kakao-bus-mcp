from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import os

# 1. 서버 이름
mcp = FastMCP("BusRam")

# 2. 키 설정
ENCODING_KEY = "ezGwhdiNnVtd%2BHvkfiKgr%2FZ4r%2BgvfeUIRz%2FdVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI%2B%2FpJFoYr9Ce%2BTDg%3D%3D"
DECODING_KEY = "ezGwhdiNnVtd+HvkfiKgr/Z4r+gvfeUIRz/dVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI+/pJFoYr9Ce+TDg=="

@mcp.tool(description="정류장 이름을 검색해서 ID와 ARS 번호를 찾습니다. 사용자가 '강남역' 등을 물어볼 때 사용합니다.")
def search_station(keyword: str) -> str:
    """[1단계] 정류장 검색"""
    url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
    
    # 👇 [수정] URL에 직접 넣지 않고, params 딕셔너리를 사용합니다. (한글 깨짐 방지)
    params = {
        "serviceKey": DECODING_KEY,
        "cityCode": "11", # 서울
        "nodeNm": keyword, # 여기에 '강남역'이 들어가도 라이브러리가 알아서 변환해줍니다.
        "numOfRows": 5,
        "_type": "json"
    }
    
    try:
        # verify=False는 SSL 인증서 에러 방지용 (Render 환경 대응)
        response = requests.get(url, params=params, timeout=10)
        
        try: data = response.json()
        except: return f"공공데이터 오류(텍스트): {response.text}"
        
        if 'response' not in data: return f"API 에러: {data}"
        header = data['response']['header']
        if header['resultCode'] != '00': return f"에러: {header['resultMsg']}"
        
        body = data['response']['body']
        if body['totalCount'] == 0: 
            return f"'{keyword}' 검색 결과가 없습니다. (서울 지역 아님?)"
        
        items = body['items']['item']
        if isinstance(items, dict): items = [items]
        
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
    url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"
    
    # 👇 [수정] params 사용
    params = {
        "serviceKey": DECODING_KEY,
        "cityCode": city_code,
        "nodeId": station_id,
        "numOfRows": 10,
        "_type": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        try: data = response.json()
        except: return f"공공데이터 오류: {response.text}"
        
        if 'response' not in data: return f"API 에러: {data}"
        header = data['response']['header']
        if header['resultCode'] != '00': return f"에러: {header['resultMsg']}"
        
        body = data['response']['body']
        if body['totalCount'] == 0: return "현재 도착 예정인 버스가 없습니다."
        
        items = body['items']['item']
        if isinstance(items, dict): items = [items]
        
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

# ---------------------------------------------------------
# 3. Starlette 서버 설정 (이전과 동일)
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    mcp_server = mcp._mcp_server
    sse = SseServerTransport("/mcp")

    async def handle_sse_connect(request):
        print("🔌 [GET] 연결 시도")
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())

    async def handle_sse_message(request):
        if "session_id" not in request.query_params:
            return JSONResponse({"status": "healthy"}, status_code=200)
        try:
            await sse.handle_post_message(request.scope, request.receive, request._send)
        except Exception as e:
            print(f"Error: {e}")

    async def handle_root(request):
        return JSONResponse({"status": "ok", "service": "BusRam MCP"})

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
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
    
    # 로컬 테스트용 실행 코드 (Render는 uvicorn 명령어로 실행됨)
    # python server.py 로 실행할 때만 작동
    import sys
    if "uvicorn" not in sys.modules:
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)