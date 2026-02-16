require("dotenv").config();
const express = require("express");
const cors = require("cors");
const axios = require("axios");

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3000;

app.get("/", (req, res) => {
  res.send("📚 bookall 서버 실행중");
});

app.get("/search", async (req, res) => {

  const keyword = req.query.keyword;
  if (!keyword) {
    return res.status(400).json({ error: "keyword 필요" });
  }

  try {

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

    const results = response.data.items.map(item => {

      const pc = Math.floor(Math.random() * 5000);
      const mobile = Math.floor(Math.random() * 5000);
      const total = pc + mobile;

      return {
        title: item.title.replace(/<[^>]*>/g, ""),
        total: total,
        storeCount: Math.floor(Math.random()*4)+1,
        category: item.category || "기타",
        link: item.link
      };
    });

    res.json(results);

  } catch (err) {
    console.error(err.message);
    res.status(500).json({ error: "검색 실패" });
  }
});

app.listen(PORT, () => {
  console.log(`🚀 서버 실행중 ${PORT}`);
});
