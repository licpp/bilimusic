const { createApp, ref, reactive, computed, onMounted, watch, nextTick } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

// --- Player Logic ---
const playerState = reactive({
    currentSong: null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    volume: 1.0,
    mode: 'sequence', // sequence, loop, random
    playlist: [],
    currentIndex: -1,
    showPlayer: false // To show/hide player bar if needed, or always show
});

class MusicPlayer {
    constructor(state) {
        this.state = state;
        this.audio = new Audio();
        this.setupEvents();
    }

    setupEvents() {
        this.audio.addEventListener('timeupdate', () => {
            this.state.currentTime = this.audio.currentTime;
            this.state.duration = this.audio.duration || 0;
        });

        this.audio.addEventListener('ended', () => {
            this.next();
        });

        this.audio.addEventListener('error', (e) => {
            console.error("Audio error", e);
            ElMessage.error("Playback error");
        });

        this.audio.addEventListener('play', () => this.state.isPlaying = true);
        this.audio.addEventListener('pause', () => this.state.isPlaying = false);
    }

    loadPlaylist(songs, startIndex = 0) {
        this.state.playlist = songs;
        this.play(startIndex);
    }

    async play(index) {
        if (index < 0 || index >= this.state.playlist.length) return;

        this.state.currentIndex = index;
        const song = this.state.playlist[index];
        this.state.currentSong = song;

        try {
            // Get audio URL
            const resp = await axios.get('/api/audio_url', {
                params: {
                    bvid: song.bvid,
                    cid: song.cid,
                },
            });
            const data = resp.data;
            if (data.error) {
                ElMessage.error("Failed to get audio: " + data.error);
                return;
            }

            const proxyUrl = `/stream?url=${encodeURIComponent(data.url)}`;
            this.audio.src = proxyUrl;
            this.audio.volume = this.state.volume;
            await this.audio.play();
        } catch (e) {
            console.error(e);
            ElMessage.error("Playback failed");
        }
    }

    togglePlay() {
        if (this.audio.paused) {
            if (this.audio.src) this.audio.play();
            else if (this.state.playlist.length > 0) this.play(this.state.currentIndex !== -1 ? this.state.currentIndex : 0);
        } else {
            this.audio.pause();
        }
    }

    next() {
        if (this.state.playlist.length === 0) return;
        let nextIndex = this.state.currentIndex;

        if (this.state.mode === 'loop') {
            this.audio.currentTime = 0;
            this.audio.play();
            return;
        } else if (this.state.mode === 'random') {
            nextIndex = Math.floor(Math.random() * this.state.playlist.length);
        } else {
            nextIndex = this.state.currentIndex + 1;
            if (nextIndex >= this.state.playlist.length) nextIndex = 0;
        }
        this.play(nextIndex);
    }

    prev() {
        if (this.state.playlist.length === 0) return;
        let prevIndex = this.state.currentIndex - 1;
        if (prevIndex < 0) prevIndex = this.state.playlist.length - 1;
        this.play(prevIndex);
    }

    seek(time) {
        if (this.audio.src) this.audio.currentTime = time;
    }

    setVolume(val) {
        this.state.volume = val;
        this.audio.volume = val;
    }

    toggleMode() {
        const modes = ['sequence', 'loop', 'random'];
        const idx = modes.indexOf(this.state.mode);
        this.state.mode = modes[(idx + 1) % modes.length];
    }
}

const player = new MusicPlayer(playerState);
let qrTimer = null;

// --- Vue App ---
const App = {
    setup() {
        // Data
        const playlists = ref([]);
        const currentView = ref('search'); // search, playlist
        const activePlaylistId = ref(null);
        const searchKeyword = ref('');
        const searchResults = ref([]);
        const searchLoading = ref(false);
        const searchPage = ref(1);
        const searchHasMore = ref(false);
        const activePlaylist = computed(() => playlists.value.find(p => p.id === activePlaylistId.value));
        const favoritePlaylist = computed(() => playlists.value.find(p => p.id === 'favorite' || p.name === 'My Favorite'));

        const loginInfo = ref({ logged_in: false, dedeuserid: null, user: null });
        const isLoggedIn = computed(() => !!loginInfo.value.logged_in);
        const userInfo = computed(() => loginInfo.value.user || null);

        const loginDialogVisible = ref(false);
        const qrSessionId = ref(null);
        const qrImage = ref('');
        const qrStatusText = ref('');
        const qrLoading = ref(false);

        const smsSessionId = ref(null);
        const smsPhone = ref('');
        const smsCode = ref('');
        const smsSecureCode = ref('');
        const smsStep = ref('idle'); // idle, geetest, code, secure
        const smsGeetestUrl = ref('');
        const smsSecureGeetestUrl = ref('');
        const smsLoading = ref(false);
        const smsStatusText = ref('');

        const userDialogVisible = ref(false);

        // Modal Data
        const videoDetailsVisible = ref(false);
        const currentVideoDetails = ref(null);
        const selectedPages = ref([]); // Array of cids

        // Initialization
        const init = async () => {
            await refreshPlaylists();
            await refreshLoginStatus();
        };

        const refreshPlaylists = async () => {
            const resp = await axios.get('/api/playlists');
            let list = resp.data || [];
            const idx = list.findIndex(p => p.id === 'favorite' || p.name === 'My Favorite');
            if (idx > 0) {
                const fav = list.splice(idx, 1)[0];
                list.unshift(fav);
            }
            playlists.value = list;
        };

        // Navigation
        const goSearch = () => {
            currentView.value = 'search';
            activePlaylistId.value = null;
        };

        const goPlaylist = (id) => {
            currentView.value = 'playlist';
            activePlaylistId.value = id;
        };

        // Search
        const fetchSearchPage = async (page) => {
            if (!searchKeyword.value) return;
            currentView.value = 'search';
            activePlaylistId.value = null;
            searchLoading.value = true;
            try {
                const resp = await axios.get('/api/search', {
                    params: {
                        keyword: searchKeyword.value,
                        page,
                    },
                });
                const res = resp.data;
                if (res.error) {
                    ElMessage.error(res.error);
                    searchResults.value = [];
                    searchHasMore.value = false;
                } else {
                    searchResults.value = res.items || [];
                    searchPage.value = res.page || page;
                    searchHasMore.value = !!res.has_more;
                }
            } catch (e) {
                ElMessage.error("Search failed");
            } finally {
                searchLoading.value = false;
            }
        };

        const doSearch = async () => {
            if (!searchKeyword.value) return;
            await fetchSearchPage(1);
        };

        const nextSearchPage = async () => {
            if (searchLoading.value) return;
            if (!searchHasMore.value) return;
            await fetchSearchPage(searchPage.value + 1);
        };

        const prevSearchPage = async () => {
            if (searchLoading.value) return;
            if (searchPage.value <= 1) return;
            await fetchSearchPage(searchPage.value - 1);
        };

        // Playlist Management
        const createPlaylist = async () => {
            try {
                const { value } = await ElMessageBox.prompt('Please enter playlist name', 'Create Playlist', {
                    confirmButtonText: 'Create',
                    cancelButtonText: 'Cancel',
                });
                if (value) {
                    await axios.post('/api/playlists', { name: value });
                    await refreshPlaylists();
                    ElMessage.success('Playlist created');
                }
            } catch (e) {
                // Cancelled
            }
        };

        const deletePlaylist = async (id) => {
            try {
                await ElMessageBox.confirm('Are you sure to delete this playlist?', 'Warning', {
                    confirmButtonText: 'Delete',
                    cancelButtonText: 'Cancel',
                    type: 'warning',
                });
                await axios.delete(`/api/playlists/${id}`);
                if (activePlaylistId.value === id) goSearch();
                await refreshPlaylists();
                ElMessage.success('Playlist deleted');
            } catch (e) {
                // Cancelled
            }
        };

        const removeSong = async (uuid) => {
            if (!activePlaylistId.value) return;
            await axios.delete(`/api/playlists/${activePlaylistId.value}/songs/${uuid}`);
            await refreshPlaylists(); // Refresh to get updated songs
        };

        // Player Interactions
        const playSongInPlaylist = (index) => {
            if (!activePlaylist.value) return;
            player.loadPlaylist(activePlaylist.value.songs, index);
        };

        const quickPlay = async (bvid) => {
            const resp = await axios.get(`/api/videos/${bvid}`);
            const info = resp.data;
            if (info.error) {
                ElMessage.error(info.error);
                return;
            }

            let songs = [];
            info.pages.forEach(page => {
                songs.push({
                    bvid: info.bvid,
                    cid: page.cid,
                    title: info.pages.length > 1 ? page.part : info.title,
                    artist: info.owner,
                    duration: formatTime(page.duration),
                    cover: info.pic,
                    uuid: crypto.randomUUID()
                });
            });

            player.loadPlaylist(songs, 0);
        };

        const isFavoritePlaylist = (p) => {
            return p && (p.id === 'favorite' || p.name === 'My Favorite');
        };

        const isFavoriteBvid = (bvid) => {
            if (!favoritePlaylist.value || !favoritePlaylist.value.songs) return false;
            return favoritePlaylist.value.songs.some(s => s.bvid === bvid);
        };

        const toggleFavoriteFromSearch = async (item) => {
            try {
                const resp = await axios.get(`/api/videos/${item.bvid}`);
                const info = resp.data;
                if (info.error) {
                    ElMessage.error(info.error);
                    return;
                }

                if (!info.pages || info.pages.length === 0) return;
                const page = info.pages[0];

                if (!favoritePlaylist.value) {
                    ElMessage.warning('Favorite playlist not ready');
                    return;
                }

                const fav = favoritePlaylist.value;
                let existing = null;
                if (fav.songs && fav.songs.length) {
                    existing = fav.songs.find(s => s.bvid === info.bvid && s.cid === page.cid);
                }

                if (existing) {
                    await axios.delete(`/api/playlists/${fav.id}/songs/${existing.uuid}`);
                    ElMessage.success('Removed from My Favorite');
                } else {
                    const song = {
                        bvid: info.bvid,
                        cid: page.cid,
                        title: info.pages.length > 1 ? page.part : info.title,
                        artist: info.owner,
                        duration: formatTime(page.duration),
                        cover: info.pic,
                    };
                    await axios.post(`/api/playlists/${fav.id}/songs`, song);
                    ElMessage.success('Added to My Favorite');
                }

                await refreshPlaylists();
            } catch (e) {
                ElMessage.error('Favorite operation failed');
            }
        };

        const isCurrentFavorite = computed(() => {
            if (!playerState.currentSong || !favoritePlaylist.value || !favoritePlaylist.value.songs) return false;
            return favoritePlaylist.value.songs.some(s => s.bvid === playerState.currentSong.bvid && s.cid === playerState.currentSong.cid);
        });

        const toggleFavoriteCurrent = async () => {
            if (!playerState.currentSong || !favoritePlaylist.value) return;
            const fav = favoritePlaylist.value;
            const current = playerState.currentSong;
            let existing = null;
            if (fav.songs && fav.songs.length) {
                existing = fav.songs.find(s => s.bvid === current.bvid && s.cid === current.cid);
            }

            try {
                if (existing) {
                    await axios.delete(`/api/playlists/${fav.id}/songs/${existing.uuid}`);
                    ElMessage.success('Removed from My Favorite');
                } else {
                    const song = {
                        bvid: current.bvid,
                        cid: current.cid,
                        title: current.title,
                        artist: current.artist,
                        duration: current.duration,
                        cover: current.cover,
                    };
                    await axios.post(`/api/playlists/${fav.id}/songs`, song);
                    ElMessage.success('Added to My Favorite');
                }
                await refreshPlaylists();
            } catch (e) {
                ElMessage.error('Favorite operation failed');
            }
        };

        // Add to Playlist Logic
        const openVideoDetails = async (bvid) => {
            const resp = await axios.get(`/api/videos/${bvid}`);
            const info = resp.data;
            if (info.error) {
                ElMessage.error(info.error);
                return;
            }
            currentVideoDetails.value = info;
            selectedPages.value = []; // Reset selection
            videoDetailsVisible.value = true;
        };

        const addToPlaylist = async (targetPlaylistId, songs) => {
            for (const song of songs) {
                await axios.post(`/api/playlists/${targetPlaylistId}/songs`, song);
            }
            ElMessage.success(`Added ${songs.length} songs`);
            videoDetailsVisible.value = false;
            await refreshPlaylists();
        };

        const handleAddSelected = async () => {
            if (!currentVideoDetails.value) return;

            // If no pages selected, warn? Or add all?
            // Let's say if none selected, add all.
            let pagesToAdd = [];
            if (selectedPages.value.length === 0) {
                pagesToAdd = currentVideoDetails.value.pages;
            } else {
                pagesToAdd = currentVideoDetails.value.pages.filter(p => selectedPages.value.includes(p.cid));
            }

            const songs = pagesToAdd.map(page => ({
                bvid: currentVideoDetails.value.bvid,
                cid: page.cid,
                title: currentVideoDetails.value.pages.length > 1 ? page.part : currentVideoDetails.value.title,
                artist: currentVideoDetails.value.owner,
                duration: formatTime(page.duration),
                cover: currentVideoDetails.value.pic
            }));

            // Ask which playlist
            if (playlists.value.length === 0) {
                ElMessage.warning("No playlists available. Create one first.");
                return;
            }

            // If we are currently viewing a playlist, maybe add to it directly?
            // Or show a selector. Selector is safer.
            // We can use a simple message box with options? No, Element Plus doesn't have a select prompt easily.
            // We'll use a custom logic or just pick the first one if only one.
            // Let's show a simple prompt using ElMessageBox with HTML? Or just a second modal?
            // For simplicity, let's just add to the *currently active* playlist if there is one,
            // otherwise prompt to select (or just default to first).
            // Better: Show a "Select Playlist" dialog.
            // I'll add a `playlistSelectionVisible` state.

            playlistSelectionSongs.value = songs;
            playlistSelectionVisible.value = true;
        };

        const playlistSelectionVisible = ref(false);
        const playlistSelectionSongs = ref([]);

        const queueVisible = ref(false);

        const confirmAddToPlaylist = async (pid) => {
            await addToPlaylist(pid, playlistSelectionSongs.value);
            playlistSelectionVisible.value = false;
        };

        const openQueue = () => {
            if (!playerState.playlist || !playerState.playlist.length) return;
            queueVisible.value = true;
        };

        const playFromQueue = (index) => {
            if (!playerState.playlist || index < 0 || index >= playerState.playlist.length) return;
            player.play(index);
        };

        // Utils
        const formatTime = (seconds) => {
            if (!seconds || isNaN(seconds)) return "0:00";
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            return `${m}:${s.toString().padStart(2, '0')}`;
        };

        const refreshLoginStatus = async () => {
            try {
                const resp = await axios.get('/api/login/info');
                loginInfo.value = resp.data || { logged_in: false };
            } catch (e) {
                loginInfo.value = { logged_in: false };
            }
        };

        const startQrLogin = async () => {
            qrLoading.value = true;
            qrStatusText.value = '正在生成二维码...';
            try {
                const resp = await axios.post('/api/login/qrcode/start');
                qrSessionId.value = resp.data.session_id;
                qrImage.value = resp.data.qrcode_image;
                qrStatusText.value = '请使用 Bilibili 手机 App 扫码登录';
                if (qrTimer) {
                    clearInterval(qrTimer);
                    qrTimer = null;
                }
                qrTimer = setInterval(async () => {
                    if (!qrSessionId.value) return;
                    try {
                        const r = await axios.get('/api/login/qrcode/status', {
                            params: { session_id: qrSessionId.value },
                        });
                        const status = r.data.status;
                        if (status === 'scan') {
                            qrStatusText.value = '已扫描，请在手机上确认登录';
                        } else if (status === 'confirm') {
                            qrStatusText.value = '请在手机上确认登录';
                        } else if (status === 'timeout') {
                            qrStatusText.value = '二维码已过期，请点击按钮重新获取';
                            clearInterval(qrTimer);
                            qrTimer = null;
                        } else if (status === 'done') {
                            qrStatusText.value = '登录成功';
                            clearInterval(qrTimer);
                            qrTimer = null;
                            ElMessage.success('登录成功');
                            await refreshLoginStatus();
                            loginDialogVisible.value = false;
                        }
                    } catch (e) {
                        // ignore single poll error
                    }
                }, 1500);
            } catch (e) {
                qrStatusText.value = '生成二维码失败';
                ElMessage.error('生成二维码失败');
            } finally {
                qrLoading.value = false;
            }
        };

        const openLoginDialog = async () => {
            loginDialogVisible.value = true;
            qrImage.value = '';
            qrStatusText.value = '';
            smsSessionId.value = null;
            smsPhone.value = '';
            smsCode.value = '';
            smsSecureCode.value = '';
            smsStep.value = 'idle';
            smsGeetestUrl.value = '';
            smsSecureGeetestUrl.value = '';
            smsStatusText.value = '';
            await startQrLogin();
        };

        const openUserDialog = () => {
            if (!loginInfo.value.logged_in) {
                openLoginDialog();
                return;
            }
            userDialogVisible.value = true;
        };

        const startSmsLogin = async () => {
            if (!smsPhone.value) {
                ElMessage.warning('请输入手机号');
                return;
            }
            smsLoading.value = true;
            smsStatusText.value = '';
            try {
                const resp = await axios.post('/api/login/sms/geetest/start');
                smsSessionId.value = resp.data.session_id;
                smsGeetestUrl.value = resp.data.geetest_url;
                smsStep.value = 'geetest';
                try {
                    window.open(smsGeetestUrl.value, '_blank');
                } catch (e) {
                    // ignore
                }
                smsStatusText.value = '请在新打开的页面完成验证码';
            } catch (e) {
                ElMessage.error('获取验证码失败');
            } finally {
                smsLoading.value = false;
            }
        };

        const logout = async () => {
            try {
                await axios.post('/api/logout');
                loginInfo.value = { logged_in: false, dedeuserid: null, user: null };
                userDialogVisible.value = false;
                ElMessage.success('已退出登录');
            } catch (e) {
                ElMessage.error('退出登录失败');
            }
        };

        const sendSmsCode = async () => {
            if (!smsSessionId.value) return;
            if (!smsPhone.value) {
                ElMessage.warning('请输入手机号');
                return;
            }
            smsLoading.value = true;
            try {
                const resp = await axios.post('/api/login/sms/send_code', {
                    session_id: smsSessionId.value,
                    phone: smsPhone.value,
                });
                if (resp.data.status === 'sms_sent') {
                    smsStep.value = 'code';
                    smsStatusText.value = '验证码已发送，请查收短信';
                } else {
                    smsStatusText.value = '发送验证码失败';
                }
            } catch (e) {
                ElMessage.error('发送验证码失败');
            } finally {
                smsLoading.value = false;
            }
        };

        const checkSmsGeetest = async () => {
            if (!smsSessionId.value) return;
            smsLoading.value = true;
            try {
                const resp = await axios.get('/api/login/sms/geetest/status', {
                    params: { session_id: smsSessionId.value },
                });
                if (resp.data.done) {
                    await sendSmsCode();
                } else {
                    smsStatusText.value = '验证码尚未完成，请先完成页面中的验证';
                }
            } catch (e) {
                ElMessage.error('检查验证码状态失败');
            } finally {
                smsLoading.value = false;
            }
        };

        const submitSmsCode = async () => {
            if (!smsSessionId.value || !smsCode.value) {
                ElMessage.warning('请输入短信验证码');
                return;
            }
            smsLoading.value = true;
            smsStatusText.value = '';
            try {
                const resp = await axios.post('/api/login/sms/verify', {
                    session_id: smsSessionId.value,
                    code: smsCode.value,
                });
                if (resp.data.status === 'done') {
                    ElMessage.success('登录成功');
                    await refreshLoginStatus();
                    loginDialogVisible.value = false;
                } else if (resp.data.status === 'need_verify') {
                    smsStep.value = 'secure';
                    smsSecureGeetestUrl.value = resp.data.geetest_url;
                    try {
                        window.open(smsSecureGeetestUrl.value, '_blank');
                    } catch (e) {
                        // ignore
                    }
                    smsStatusText.value = '需要进行安全验证，请在新页面完成并输入短信验证码';
                } else {
                    smsStatusText.value = '登录失败';
                }
            } catch (e) {
                ElMessage.error('登录失败');
            } finally {
                smsLoading.value = false;
            }
        };

        const submitSmsSecureCode = async () => {
            if (!smsSessionId.value || !smsSecureCode.value) {
                ElMessage.warning('请输入安全验证短信验证码');
                return;
            }
            smsLoading.value = true;
            try {
                const resp = await axios.post('/api/login/sms/verify_complete', {
                    session_id: smsSessionId.value,
                    code: smsSecureCode.value,
                });
                if (resp.data.status === 'done') {
                    ElMessage.success('登录成功');
                    await refreshLoginStatus();
                    loginDialogVisible.value = false;
                } else {
                    smsStatusText.value = '安全验证失败';
                }
            } catch (e) {
                ElMessage.error('安全验证失败');
            } finally {
                smsLoading.value = false;
            }
        };

        onMounted(() => {
            init();
        });

        watch(loginDialogVisible, (val) => {
            if (!val && qrTimer) {
                clearInterval(qrTimer);
                qrTimer = null;
            }
        });

        return {
            // State
            playlists,
            currentView,
            activePlaylistId,
            activePlaylist,
            favoritePlaylist,
            loginInfo,
            isLoggedIn,
            userInfo,
            loginDialogVisible,
            searchKeyword,
            searchResults,
            searchLoading,
            searchPage,
            searchHasMore,
            playerState,
            videoDetailsVisible,
            currentVideoDetails,
            selectedPages,
            playlistSelectionVisible,
            queueVisible,
            qrImage,
            qrStatusText,
            qrLoading,
            smsPhone,
            smsCode,
            smsSecureCode,
            smsStep,
            smsGeetestUrl,
            smsSecureGeetestUrl,
            smsLoading,
            smsStatusText,
            userDialogVisible,

            // Methods
            goSearch,
            goPlaylist,
            doSearch,
            createPlaylist,
            deletePlaylist,
            removeSong,
            playSongInPlaylist,
            quickPlay,
            openVideoDetails,
            handleAddSelected,
            confirmAddToPlaylist,
            nextSearchPage,
            prevSearchPage,
            isFavoritePlaylist,
            isFavoriteBvid,
            toggleFavoriteFromSearch,
            openQueue,
            playFromQueue,
            openLoginDialog,
            openUserDialog,
            startQrLogin,
            startSmsLogin,
            checkSmsGeetest,
            submitSmsCode,
            submitSmsSecureCode,
            logout,

            // Player Methods
            togglePlay: () => player.togglePlay(),
            next: () => player.next(),
            prev: () => player.prev(),
            seek: (val) => player.seek(val),
            setVolume: (val) => player.setVolume(val),
            toggleMode: () => player.toggleMode(),
            toggleFavoriteCurrent,
            isCurrentFavorite,

            // Icons (if needed to pass to template, but we can use global registration or string names)
            // Utils
            formatTime
        };
    }
};

const app = createApp(App);
app.use(ElementPlus);
// Register Icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component);
}
app.mount('#app');
