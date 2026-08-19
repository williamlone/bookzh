//版权信息
document.write('<a href="/archives/1.html">联系我们</a> ┊ <a href="/archives/2414.html">投放广告</a> ┊ 版权所有：深圳市南山区月光博客信息咨询部 ┊ 备案号：<a href="http://beian.miit.gov.cn/" rel="nofollow">粤ICP备16102788号-1</a>┊ Powered by：Z-Blog ');

//通栏广告
$(document).ready(function(){
//  $(".content.alpha").prepend("<center><a rel='nofollow' href='https://ngmov.me/?channelCode=ngyg93' target='_blank'><img src='/images/ads.jpg' alt='add 2020-1-7'></a></center>");
//  $(".divSearchPanel").append("<center><a rel='nofollow' href='https://www.ivacykodi.com/best-deal-offer-cn/?aff=91574' target='_blank'><img src='/images/300X250.png' border='0' alt='add 2020-1-7'></a></center>");
});


//侧栏漂浮
$.fn.smartFloat = function() {
var position = function(element) {
var top = element.position().top, pos = element.css("position");
$(window).scroll(function() {
var scrolls = $(this).scrollTop();
if (scrolls > top) {
if (window.XMLHttpRequest) {
element.css({
position: "fixed",
top: 0
});
} else {
element.css({
top: scrolls
});
}
}else {
element.css({
position: pos,
top: top
});
}
});
};
return $(this).each(function() {
position($(this));
});
};

//绑定
$("#float").smartFloat();

// Infinite Ajax Scroll v2.3.1
//document.write("<script type='text/javascript' src='/script/jquery-ias.min.js'></script> <script type='text/javascript'>var ias = jQuery.ias({container: '.content',item:      '.entry',pagination:'.pagination',next:      '.next-page'});ias.extension(new IASSpinnerExtension());ias.extension(new IASTriggerExtension({offset: 10}));ias.extension(new IASPagingExtension());ias.on('pageChange', function(pageNum, scrollOffset, url){pathurl=jQuery('<a/>').attr('href',url)[0].pathname.replace(/^[^\/]/,'/');ga('create', 'UA-272027-5', 'auto');ga('send', 'pageview', pathurl);history.pushState(null,null,url);});</script>");