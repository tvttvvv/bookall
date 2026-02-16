require("dotenv").config();
const express = require("express");
const cors = require("cors");
const axios = require("axios");
const crypto = require("crypto");

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3000;

/* ===============================
   상태 확인
================================= */
app.get("/", (req, res) => {
  res.send("📚 bookall 통합 서버 정상 작동중");
});

/* ===============================
   네이버 도서 검색
================================= */
async function searchBooks(keyword) {

  const response = await axios.get(
    "https://openapi.naver.com/v1/search/book.json",
    {
      params: { query: keyword, display: 5 },
      headers: {
        "X-Naver-Client-Id": process.env.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": process.env.NAVER_CLIENT_SECRET
      }
    }
  );

  return response.data.items;
}

/* ===============================
   🔥 검색량 조회 (네이버 광고 API용 구조)
   현재는 샘플 구조
================================= */
async function getSearchVolume(keyword) {

  // TODO: 네이버 검색광고 API 붙일 자리

  // 임시 로직 (랜덤 제거하고 안정적 숫자 생성)
  const hash = crypto.createHash("md5").update(keyword).digest("hex");
  const seed = parseInt(hash.substring(0, 8), 16);

  const pc = (seed % 4000) + 500;
  const mobile = (seed % 6000) + 1000;

  return pc + mobile;
}

/* ===============================
   판매처 개수 계산
================================= */
function getStoreCount(link) {

  // 현재는 네이버 도서 링크 기반 추정
  // 실제 크롤링 붙이면 여기에 추가

  if (!link) return 1;

  return 3; // 기본 3개로 고정 (실전에서는 크롤링)
}

/* ===============================
   통합 검색 API
================================= */
app.get("/search", async (req, res) => {

  const keyword = req.query.keyword;
  if (!keyword) {
    return res.status(400).json({ error: "keyword 필요" });
  }

  try {

    const items = await searchBooks(keyword);

    const results = await Promise.all(
      items.map(async (item) => {

        const cleanTitle = item.title.replace(/<[^>]*>/g, "");
        const total = await getSearchVolume(cleanTitle);
        const storeCount = getStoreCount(item.link);

        return {
          title: cleanTitle,
          total: total,
          storeCount: storeCount,
          category: item.category || "기타",
          link: item.link
        };
      })
    );

    res.json(results);

  } catch (err) {
    console.error(err.message);
    res.status(500).json({ error: "검색 실패" });
  }
});

/* ===============================
   서버 실행
================================= */
app.listen(PORT, "0.0.0.0", () => {
  console.log(`🚀 bookall 서버 실행중 (PORT ${PORT})`);
});
