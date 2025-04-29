import os #token.json 파일 유무여부 확인
from dotenv import load_dotenv # env파일 관리리
import streamlit as st #streamlit
import pandas as pd #유튜브 api로 가져온 데이터 정리, 표 형식으로 나타냄
from googleapiclient.discovery import build #유튜브 api를 호출할 수 있도록 클라이언트 생성
from google.oauth2.credentials import Credentials # OAuth2의 자격 증명 관리, token으로부터 자격 증명을 가져옴
from google_auth_oauthlib.flow import InstalledAppFlow  #유튜브 api에 액세스하기 위한 사용자 인증 처리
from google.auth.transport.requests import Request #자격증명이 자꾸 만료되서 갱신하기 위해 import
from youtube_transcript_api import YouTubeTranscriptApi #유튜브 자막 데이터 가져오기
from youtube_transcript_api.formatters import TextFormatter # 자막 텍스트 형변환
import openai #ChatGPT 가져오기
import isodate #동영상 길이 보기 쉽게 초단위로 조정

# OAuth 2.0 클라이언트 파일 경로 및 범위
CLIENT_SECRET_FILE = 'client_secret.json'
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly', # 읽기 접근권한 허용
    'https://www.googleapis.com/auth/youtube.force-ssl', # youtube api에 전체접근권한 제공
    'openid', # 사용자 인증
    'https://www.googleapis.com/auth/userinfo.email', # 사용자 이메일에 접근할 수 있는 권한 요청
    'https://www.googleapis.com/auth/userinfo.profile' # 사용자의 공개 프로필 정보에 접근할 수 있는 권한 요청
]

# env파일 로드
load_dotenv()

# OpenAI
openai.api_key = os.getenv("openai.api_key")

# 사용자 인증을 처리하고 토큰을 저장
def get_authenticated_service():
    creds = None # 인증 정보를 저장하는 객체
    token_file = 'token.json'

    if os.path.exists(token_file): # 토큰 파일이 존재하는지 확인
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid or not creds.refresh_token: # 토큰 유효성 검사
        if os.path.exists(token_file):
            os.remove(token_file)

        if creds and creds.expired and creds.refresh_token: # 토큰 갱신
            creds.refresh(Request())
        else: # 기존 인증 정보가 없거나 갱신이 불가능하면 새 로그인 프로세스 실행
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080, prompt='consent', access_type='offline')

        with open(token_file, 'w') as token: # 새로 발급받은 인증 정보를 저장(쓰기모드)
            token.write(creds.to_json())

    return build('youtube', 'v3', credentials=creds) # 인증 정보를 활용해 youtube api 서비스 객체를 생성, 반환

# 동영상 길이를 초로 변환하는 함수
def convert_duration_to_seconds(duration):
    parsed_duration = isodate.parse_duration(duration)
    return parsed_duration.total_seconds()

# 초를 분과 초로 변환하는 함수
def format_duration(seconds):
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes} 분 {seconds} 초"

# 유튜브 동영상 통계 정보를 가져오는 함수
def get_video_stats(youtube, min_duration=None, max_duration=None, category_id=None, limit=None):
    videos = []
    page_token = None
    max_results = 50
    target_count = limit if limit else 50

    while len(videos) < target_count:
        request = youtube.videos().list(
            part='snippet,statistics,contentDetails',
            myRating='like',
            maxResults=max_results,
            pageToken=page_token
        )
        response = request.execute()

        for video in response['items']:
            title = video['snippet']['title']
            views = int(video['statistics'].get('viewCount', 0))
            likes = int(video['statistics'].get('likeCount', 0))
            duration = video['contentDetails']['duration']
            duration_in_seconds = convert_duration_to_seconds(duration)
            formatted_duration = format_duration(duration_in_seconds)
            video_url = f"https://www.youtube.com/watch?v={video['id']}"
            video_category_id = video['snippet'].get('categoryId', None)

            if (min_duration is None or duration_in_seconds > min_duration) and \
               (max_duration is None or duration_in_seconds <= max_duration) and \
               (category_id is None or video_category_id == category_id):
                videos.append({
                    'Title': title,
                    'Views': views,
                    'Likes': likes,
                    'Duration': formatted_duration,
                    'URL': video_url,
                    'Category ID': video_category_id
                })

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    df = pd.DataFrame(videos[:target_count])
    df['Category'] = df['Category ID'].map(CATEGORY_MAP)
    return df[['Title', 'Views', 'Likes', 'Duration', 'URL', 'Category']]

# 유튜브 동영상 검색 및 정보 가져오기
def search_videos(youtube, query):
    request = youtube.search().list(
        part='snippet',
        q=query,
        type='video',
        maxResults=10
    )
    response = request.execute()
    video_data = []

    for item in response['items']:
        video_id = item['id']['videoId']
        video_details = youtube.videos().list(
            part='snippet,statistics,contentDetails',
            id=video_id
        ).execute()

        for video in video_details['items']:
            title = video['snippet']['title']
            likes = int(video['statistics'].get('likeCount', 0))
            dislikes = int(video['statistics'].get('dislikeCount', 0)) if 'dislikeCount' in video['statistics'] else "Not Available"
            comments = int(video['statistics'].get('commentCount', 0))
            upload_date = video['snippet']['publishedAt']
            category_id = video['snippet'].get('categoryId', None)
            category = CATEGORY_MAP.get(category_id, "Unknown")
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            video_data.append({
                'Title': title,
                'Likes': likes,
                'Dislikes': dislikes,
                'Comments': comments,
                'Upload Date': upload_date,
                'Category': category,
                'URL': video_url
            })

    return pd.DataFrame(video_data)

# 자막을 가져오는 함수
def get_video_captions(video_url):
    video_id = video_url.split("v=")[-1]
    
    # 자막 언어 리스트 가져오기 (가능한 모든 언어로 시도)
    try:
        transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en', 'ja'])
        text_formatter = TextFormatter()
        text_formatted = text_formatter.format_transcript(transcript_data)
        return text_formatted
    except Exception as e:
        return f"자막을 가져오는 중 오류 발생: {e}"

# GPT-4-mini를 사용하여 자막 요약
def summarize_with_gpt(text):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"다음 텍스트를 요약해줘: {text}"}
            ]
        )
        summary = response.choices[0].message['content']
        return summary
    except Exception as e:
        return f"요약 실패: {e}"

# 카테고리 ID에 대한 이름 매핑
CATEGORY_MAP = {
    '1': 'Film & Animation',
    '2': 'Autos & Vehicles',
    '10': 'Music',
    '15': 'Pets & Animals',
    '17': 'Sports',
    '18': 'Short Movies',
    '19': 'Travel & Events',
    '20': 'Gaming',
    '21': 'Videoblogging',
    '22': 'People & Blogs',
    '23': 'Comedy',
    '24': 'Entertainment',
    '25': 'News & Politics',
    '26': 'Howto & Style',
    '27': 'Education',
    '28': 'Science & Technology',
    '29': 'Nonprofits & Activism',
    '30': 'Movies',
    '31': 'Anime/Animation',
    '32': 'Action/Adventure',
    '33': 'Classics',
    '34': 'Comedy',
    '35': 'Documentary',
    '36': 'Drama',
    '37': 'Family',
    '38': 'Foreign',
    '39': 'Horror',
    '40': 'Sci-Fi/Fantasy',
    '41': 'Thriller',
    '42': 'Shorts',
    '43': 'Shows',
    '44': 'Trailers'
}

# Streamlit 애플리케이션
def main():
    page = st.sidebar.selectbox("페이지 선택", [
        "일반영상",
        "Short_영상",
        "나의 총합 알고리즘",
        "유튜브 검색",
        "자막"
    ])

    youtube = get_authenticated_service()

    df = pd.DataFrame()

    if page == "일반영상":
        st.title("일반영상")
        df = get_video_stats(youtube, min_duration=90)
    elif page == "Short_영상":
        st.title("Short_영상")
        df = get_video_stats(youtube, min_duration=0, max_duration=120)
    elif page == "나의 총합 알고리즘":
        st.title("나의 알고리즘 그래프")

        # '일반영상' 카테고리 데이터 가져오기
        general_videos_df = get_video_stats(youtube, min_duration=90)

        # 'Short_영상' 카테고리 데이터 가져오기
        short_videos_df = get_video_stats(youtube, min_duration=0, max_duration=120)

        # 각 카테고리별 동영상 수 계산
        general_category_counts = general_videos_df['Category'].value_counts()
        short_category_counts = short_videos_df['Category'].value_counts()

        # Streamlit의 기본 제공 원형 그래프
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("일반영상 카테고리 분포")
            st.plotly_chart({
                "data": [{"values": general_category_counts.values, "labels": general_category_counts.index, "type": "pie"}],
                "layout": {"title": "일반영상 카테고리 분포"}
            })

        with col2:
            st.subheader("Short_영상 카테고리 분포")
            st.plotly_chart({
                "data": [{"values": short_category_counts.values, "labels": short_category_counts.index, "type": "pie"}],
                "layout": {"title": "Short_영상 카테고리 분포"}
            })
    elif page == "유튜브 검색":
        st.title("유튜브 검색")
        query = st.text_input("검색어를 입력하세요")
        if query:
            df = search_videos(youtube, query)

    if not df.empty:
        st.dataframe(df, column_config={
            "URL": st.column_config.LinkColumn("유튜브 링크")
        })

    # 자막 페이지
    elif page == "자막":
        st.title("자막 요약")
        video_url = st.text_input("유튜브 동영상 URL을 입력하세요")
        if video_url:
            captions = get_video_captions(video_url)
            st.write("자막:")
            st.text_area("", captions, height=300)

            if st.button("GPT로 자막 요약"):
                summary = summarize_with_gpt(captions)
                st.write("요약 결과:")
                st.text_area("", summary, height=150)

if __name__ == "__main__":
    main()
