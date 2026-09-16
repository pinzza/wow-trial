"""WCL V2 GraphQL API 客户端"""
import time
import asyncio
import httpx
from wcl_parser.exceptions import WCLAPIError, WCLAuthError, WCLRateLimitError

WCL_API_URL = "https://cn.warcraftlogs.com/api/v2/client"
WCL_AUTH_URL = "https://cn.warcraftlogs.com/oauth/token"


class V2Client:
    def __init__(self, client_id: str, client_secret: str,
                 rate_limit_per_minute: int = 100):
        self.client_id = client_id
        self.client_secret = client_secret
        self.rate_limit = rate_limit_per_minute
        self._token: str = ''
        self._token_expires: float = 0.0
        self._last_request: float = 0.0

    async def __aenter__(self):
        await self.authenticate()
        return self

    async def __aexit__(self, *args):
        pass

    async def authenticate(self):
        """OAuth 获取 access_token"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(WCL_AUTH_URL, data={
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            }, timeout=30.0)
            if resp.status_code != 200:
                raise WCLAuthError(
                    f"OAuth 认证失败: {resp.status_code} {resp.text}",
                    resp.status_code
                )
            data = resp.json()
            self._token = data['access_token']
            self._token_expires = time.time() + data.get('expires_in', 86400)

    async def _throttle(self):
        """限速控制: 确保两次请求间隔 >= 60/rate_limit 秒"""
        elapsed = time.time() - self._last_request
        min_interval = 60.0 / self.rate_limit
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request = time.time()

    async def _graphql(self, query: str, variables: dict) -> dict:
        """执行 GraphQL 查询，带重试"""
        await self._throttle()
        headers = {
            'Authorization': f'Bearer {self._token}',
            'Content-Type': 'application/json',
        }
        payload = {'query': query, 'variables': variables}
        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        WCL_API_URL, json=payload, headers=headers
                    )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get('Retry-After', 5))
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code == 401:
                    await self.authenticate()
                    headers['Authorization'] = f'Bearer {self._token}'
                    continue
                if resp.status_code >= 400:
                    raise WCLAPIError(
                        f"GraphQL 请求失败: {resp.status_code} {resp.text[:500]}",
                        resp.status_code
                    )
                data = resp.json()
                if 'errors' in data:
                    raise WCLAPIError(
                        f"GraphQL 错误: {data['errors']}"
                    )
                return data
            except httpx.TimeoutException as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
            except httpx.NetworkError as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
        raise WCLAPIError(f"GraphQL 请求重试耗尽: {last_error}")

    async def query_report(self, report_code: str) -> dict:
        """查询报告元数据 + 战斗列表"""
        query = '''
        query($code: String!) {
          reportData {
            report(code: $code) {
              code
              title
              startTime
              endTime
              zone { name }
              owner { name }
              fights(killType: Encounters) {
                id name kill difficulty startTime endTime fightPercentage
              }
            }
          }
        }'''
        return await self._graphql(query, {'code': report_code})

    async def query_player_table(self, report_code: str, fight_ids: list[int],
                                  data_type: str = 'DamageDone') -> dict:
        """查询玩家统计表 (DamageDone / Healing / DamageTaken)"""
        query = '''
        query($code: String!, $fights: [Int!], $type: TableDataType!) {
          reportData {
            report(code: $code) {
              table(fightIDs: $fights, dataType: $type)
            }
          }
        }'''
        return await self._graphql(query, {
            'code': report_code,
            'fights': fight_ids,
            'type': data_type,
        })

    async def query_events(self, report_code: str, fight_ids: list[int],
                            start_time: int, end_time: int,
                            limit: int = 10000) -> dict:
        """查询战斗事件流 (分页用 nextPageTimestamp)"""
        query = '''
        query($code: String!, $fights: [Int!], $start: Float!, $end: Float!,
              $limit: Int!) {
          reportData {
            report(code: $code) {
              events(fightIDs: $fights, startTime: $start, endTime: $end,
                     limit: $limit) {
                data
                nextPageTimestamp
              }
            }
          }
        }'''
        return await self._graphql(query, {
            'code': report_code,
            'fights': fight_ids,
            'start': start_time,
            'end': end_time,
            'limit': limit,
        })


if __name__ == '__main__':
    import inspect
    # 结构验证: 测试类定义和方法签名
    assert hasattr(V2Client, 'authenticate'), "缺少 authenticate 方法"
    assert hasattr(V2Client, 'query_report'), "缺少 query_report 方法"
    assert hasattr(V2Client, 'query_player_table'), "缺少 query_player_table 方法"
    assert hasattr(V2Client, 'query_events'), "缺少 query_events 方法"
    sig = inspect.signature(V2Client.__init__)
    params = list(sig.parameters.keys())
    assert 'client_id' in params, "V2Client 缺少 client_id 参数"
    assert 'client_secret' in params, "V2Client 缺少 client_secret 参数"
    print("V2Client 结构验证通过")
    print(f"  __init__ 参数: {params}")
    print(f"  GraphQL 查询: query_report, query_player_table, query_events")
