---
title: "Search"
date: 2024-01-01
---

<div id="search-container">
  <input type="text" id="search-input" placeholder="Type to search..." autofocus>
  <div id="search-results"></div>
</div>

<style>
#search-container {
  max-width: 800px;
  margin: 0 auto;
}
#search-input {
  width: 100%;
  padding: 12px 16px;
  font-size: 18px;
  border: 2px solid #ddd;
  border-radius: 8px;
  margin-bottom: 20px;
  box-sizing: border-box;
}
#search-input:focus {
  outline: none;
  border-color: #0066cc;
}
#search-results {
  list-style: none;
  padding: 0;
}
.search-result {
  padding: 16px;
  margin-bottom: 12px;
  border: 1px solid #eee;
  border-radius: 8px;
  background: #fafafa;
}
.search-result:hover {
  background: #f0f0f0;
}
.search-result h3 {
  margin: 0 0 8px 0;
}
.search-result h3 a {
  color: #0066cc;
  text-decoration: none;
}
.search-result h3 a:hover {
  text-decoration: underline;
}
.search-result .section {
  display: inline-block;
  padding: 2px 8px;
  background: #e0e0e0;
  border-radius: 4px;
  font-size: 12px;
  margin-bottom: 8px;
  text-transform: capitalize;
}
.search-result .snippet {
  color: #666;
  font-size: 14px;
  line-height: 1.5;
}
.no-results {
  color: #666;
  font-style: italic;
}
</style>

<script src="https://cdn.jsdelivr.net/npm/fuse.js@7.0.0"></script>
<script>
(function() {
  let fuse = null;
  let searchData = [];

  // Fetch the search index (relative to baseURL)
  const baseUrl = document.querySelector('base')?.href || window.location.origin + '/iops/';
  fetch(baseUrl + 'index.json')
    .then(response => response.json())
    .then(data => {
      searchData = data;
      fuse = new Fuse(data, {
        keys: ['title', 'content'],
        includeScore: true,
        threshold: 0.4,
        ignoreLocation: true
      });
    })
    .catch(err => {
      console.error('Failed to load search index:', err);
      document.getElementById('search-results').innerHTML =
        '<p class="no-results">Failed to load search index. Please try again later.</p>';
    });

  const searchInput = document.getElementById('search-input');
  const searchResults = document.getElementById('search-results');

  let debounceTimer;
  searchInput.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(performSearch, 200);
  });

  function performSearch() {
    const query = searchInput.value.trim();

    if (!query) {
      searchResults.innerHTML = '';
      return;
    }

    if (!fuse) {
      searchResults.innerHTML = '<p class="no-results">Loading search index...</p>';
      return;
    }

    const results = fuse.search(query);

    if (results.length === 0) {
      searchResults.innerHTML = '<p class="no-results">No results found for "' + escapeHtml(query) + '"</p>';
      return;
    }

    let html = '';
    results.slice(0, 20).forEach(result => {
      const item = result.item;
      const snippet = item.content ? item.content.substring(0, 200) + '...' : '';
      html += '<div class="search-result">';
      html += '<h3><a href="' + item.url + '">' + escapeHtml(item.title) + '</a></h3>';
      if (item.section) {
        html += '<span class="section">' + escapeHtml(item.section) + '</span>';
      }
      html += '<p class="snippet">' + escapeHtml(snippet) + '</p>';
      html += '</div>';
    });

    searchResults.innerHTML = html;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
})();
</script>
