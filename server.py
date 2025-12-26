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
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    
    # 1. FastMCP 내부의 진짜 서버 객체를 꺼냅니다.
    # (에러 로그가 알려준 _mcp_server 속성을 사용합니다)
    server = mcp._mcp_server

    async def handle_sse(request):
        # SSE 통신을 위한 연결 통로 설정
        transport = SseServerTransport("/sse")
        async with transport.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )

    # 2. 웹 서버(Starlette)를 직접 만듭니다.
    starlette_app = Starlette(
        debug=True,
        routes=[Route("/sse", endpoint=handle_sse)]
    )

    # 3. Render에서 주는 포트 번호를 받습니다.
    port = int(os.environ.get("PORT", 8000))
    
    print(f"Render 배포용 서버 시작! (0.0.0.0:{port})")
    
    # 4. 강제로 0.0.0.0 주소로 실행합니다.
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)