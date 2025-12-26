from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import os

# 1. 서버 이름 설정
mcp = FastMCP("BusAlert")

# 2. 님의 키 (Encoding 키)
ENCODING_KEY = "ezGwhdiNnVtd%2BHvkfiKgr%2FZ4r%2BgvfeUIRz%2FdVqEMTaJuAyXxGiv0pzK0P5YT37c4ylzS7kI%2B%2FpJFoYr9Ce%2BTDg%3D%3D"

# 공공데이터포털은 Decoding된 키를 원하므로 미리 변환
DECODING_KEY = urllib.parse.unquote(ENCODING_KEY)

@mcp.tool()
def search_station(keyword: str) -> str:
    """
    [1단계] 정류장 이름을 검색해서 ID를 찾습니다.
    예: "강남역"을 검색하면 정류장 ID와 도시 코드를 알려줍니다.
    Args:
        keyword: 검색할 정류장 이름 (예: 강남역)
    """
    # [수정] https로 변경됨
    url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
    
    params = {
        "serviceKey": DECODING_KEY,
        "cityCode": "11", # 서울
        "nodeNm": keyword,
        "numOfRows": 5,
        "_type": "json"
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        items = data['response']['body']['items']['item']
        if not items:
            return "검색 결과가 없습니다."
            
        if isinstance(items, dict):
            items = [items]
            
        result = f"'{keyword}' 검색 결과:\n"
        for item in items:
            name = item.get('nodeNm')
            node_id = item.get('nodeid') 
            ars_id = item.get('nodeno')
            result += f"- {name} (ID: {node_id}) / 정류장번호: {ars_id}\n"
            
        return result
        
    except Exception as e:
        return f"에러 발생: {str(e)}"

@mcp.tool()
def check_arrival(city_code: str, station_id: str) -> str:
    """
    [2단계] 특정 정류장에 오는 버스들의 도착 정보를 조회.
    Args:
        city_code: 도시 코드 (서울: 11, 경기: 31, 세종: 12 등)
        station_id: search_station에서 찾은 정류장 ID (예: DJB8001793)
    """
    # [수정] https로 변경됨
    url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"
    
    params = {
        "serviceKey": DECODING_KEY,
        "cityCode": city_code,
        "nodeId": station_id,
        "numOfRows": 10,
        "_type": "json"
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        items = data['response']['body']['items']['item']
        if not items:
            return "현재 도착 예정인 버스가 없습니다."
            
        if isinstance(items, dict):
            items = [items]
            
        result = f"정류장(ID:{station_id}) 도착 정보:\n"
        for item in items:
            bus_num = item.get('routeno') 
            left_station = item.get('arrprevstationcnt') 
            left_time = item.get('arrtime') 
            
            min_left = int(left_time) // 60
            
            result += f"- [{bus_num}번] {min_left}분 후 도착 ({left_station}정거장 전)\n"
            
        return result

    except Exception as e:
        return f"도착 정보 조회 실패: {str(e)}"



if __name__ == "__main__":
    import uvicorn
    import os
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    
    # 1. FastMCP의 진짜 본체(Server)를 가져옵니다.
    server = mcp._mcp_server
    
    # 2. SSE 통신을 담당할 우체부(Transport)를 만듭니다.
    # [중요] 주소는 "/sse" 입니다.
    sse = SseServerTransport("/sse")

    async def handle_sse_connect(request):
        """
        [GET 요청 처리]
        AI가 처음 접속해서 "연결해주세요~" 할 때 작동합니다.
        """
        print(f"🔌 AI 접속 시도! (Client connected)")
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            # 스트림을 열고 서버를 실행합니다.
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )

    async def handle_sse_message(request):
        """
        [POST 요청 처리] - 여기가 핵심! 405 에러 해결사
        AI가 연결된 상태에서 "강남역 찾아줘"라고 명령(JSON)을 보낼 때 작동합니다.
        """
        print(f"AI 메시지 수신! (POST request)")
        await sse.handle_post_message(request.scope, request.receive, request._send)

    # 3. 웹 서버(Starlette)를 만들고 문을 두 개 엽니다. (GET, POST)
    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse_connect, methods=["GET"]),
            Route("/sse", endpoint=handle_sse_message, methods=["POST"]) # 👈 이 줄이 없어서 405가 떴던 겁니다!
        ]
    )

    # 4. Render 포트 설정
    port = int(os.environ.get("PORT", 8000))
    
    print(f"[최종 수정] 서버가 0.0.0.0:{port} 에서 시작됩니다.")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)