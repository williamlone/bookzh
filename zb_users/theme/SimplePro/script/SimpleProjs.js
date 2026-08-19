jQuery(document).ready(function($) {
var s = $('#shangxia').offset().top;
    $(window).scroll(function() {
        $("#shangxia").animate({
            top: $(window).scrollTop() + s + "px"
        },
        {
            queue: false,
            duration: 500
        })
    });
});
//搜索框默认值
sidebarloaded.add(function(){ 
	$("#edtSearch").val("Search");
	$("#edtSearch").bind({
		focus:function(){if(this.value=="Search")this.value='';},
		blur:function(){if(this.value=='')this.value="Search";},
	});
});

$('#shang').click(function(){$('html,body').animate({scrollTop: '0px'}, 800);}); 
//点击id="shang"对象时，滑动至相对浏览器滚动条为0px（即顶部），时间为800毫秒
$('#comt').click(function(){$('html,body').animate({scrollTop:$('#comments').offset().top}, 800);});
//点击id="comt"对象时，滑动至id="comment"相对浏览器滚动条的距离，时间为800毫秒
$('#xia').click(function(){$('html,body').animate({scrollTop:$('#copyright-wrap').offset().top}, 800);});
$(document).ready(function () {
	$(".themeinfo a").removeAttr("rel");
	$(".sidebar-box .tagcloud a").removeAttr("style"); 
});

$(document).ready(function(){ 
	//if($(".commentsbox .commentlist").length==0){$(".commentsbox").hide()} //隐藏空评论
	if($(".respond").length==0){$(".commentboxhide").hide()} //关闭评论时隐藏
	//try { var c=$.trim($(".mutuality_body").html());  if(!c){$(".mutuality").hide()} }catch(e) {}//隐藏空相关文章
	//$(".post_tags").each(function(){if($(this).find('a').length==0){$(this).hide()}}); //隐藏空tags
});