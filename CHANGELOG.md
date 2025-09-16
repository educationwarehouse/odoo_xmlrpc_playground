# Changelog

<!--next-version-placeholder-->

## v0.3.0 (2025-09-16)

### Feature

* Enhance task hierarchy assembly with caching and improve performance for verbose modes ([`6620dad`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/6620dadd3852d7a6fc19258c87a81c1ac18c6a6d))
* Improve performance in task manager hierarchy assembly and add timing details; disable verbose logging by default in web search server ([`a9a9522`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/a9a9522ff4377c1c088de6047943fabb72f23144))
* Add in-memory caching with TTL for user name resolution and verbose timing for task hierarchy operations ([`b18ec30`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/b18ec30f513b4216707c5eea3b24896544111340))

### Fix

* Not hookable setup, no change required on different projects ([`25f0314`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/25f0314eec3814c2dfb1f4519e57e8f6790d22ab))
* Adjust hierarchy container styling to remove inner scrolling and allow full vertical expansion ([`b0bd408`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/b0bd4085edd289836b74e9a0e4ffe6e1b27b12aa))
* Import re module to resolve undefined name errors ([`755f654`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/755f654bb061e4f7875a1fa77b85d1c26d176923))
* Implement comprehensive security hardening for Odoo plugin ([`a304e85`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/a304e85cbd69c0f4431e5cf7501e8d862c6d4883))
* Update changelog to reflect config settings adjustment for web ([`baf7dee`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/baf7dee557b53abcc2b3dd1d6197c6414884e2f8))

## v0.2.1 (2025-09-03)

* fixed config settings to use the new location for the web as well. 

## v0.2.0 (2025-09-03)

### Feature

* Add comprehensive timing instrumentation to search methods ([`ce03c7a`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/ce03c7aa3afabe673186e772c2168930e6fb1c90))
* Add markdown2 dependency and implement markdown_to_html method ([`66bb8ce`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/66bb8ce766380be204486512a76b2de2b4109972))
* Add dotenv path support to odoo plugin setup ([`adf56ba`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/adf56baf1f7115bccd713a3673389fa0f5a5aec0))
* Enhance setup function to display .env file search locations and usage ([`59171d3`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/59171d322c6d2dcb1bc29c511a05566259c8bafc))
* Add configuration change detection to setup function ([`9a4deb8`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/9a4deb89f54d032d184a3ab4bd080b4da84bcc61))
* Make Odoo connection port and protocol configurable ([`0ebcb80`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/0ebcb808e4e570d3e172ef63af6251fd21587641))
* Update setup task to support new Odoo environment variable structure with password authentication ([`9df7d10`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/9df7d105778fb8aae1e043eab23139acc1adf674))
* Enhance odoo setup task with interactive configuration and connection testing ([`a7b053b`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/a7b053ba48756eb325e57cede9b37747c528b486))
* Add setup task to create .env configuration file ([`ebd298f`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/ebd298f0f8ed7ff6de0eac93293f11556a56445a))

### Fix

* Correct search/replace blocks to match exact file content ([`2750207`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/275020705c496c4b85701923b6270fc3ed4a20b5))
* Ensure odoo config validation checks for non-empty values ([`4f72a66`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/4f72a66e042c7c478960bbc6540e4e3c9d77f58f))
* Remove create_env_file function to prevent dummy config creation ([`7001568`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7001568981fee9acffe7492a1ad6c1ea89936f47))
* Prevent .env file creation when config is already complete ([`303ae6f`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/303ae6fd4ff874e223bd395a054f583533ebdf94))
* Prevent setup from using current directory .env file ([`00789f9`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/00789f92829898bdb263e66fd6b45c50eca75300))
* Prevent creation of empty .env file in cwd during setup ([`022d831`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/022d831c5d05223f37323e34e4c64bcfe6e7e627))
* Prevent .env creation during init and improve error handling ([`9bbbf2c`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/9bbbf2c5f3de51ff3fbf7e6cdd904b0b7c2f3a2d))
* Ensure .env file creation respects config directory preference ([`5ea67a9`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/5ea67a944862d39090b99ee5e069c26bb02b8c3e))
* Suppress pkg_resources deprecation warning in search function ([`ba11c9d`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/ba11c9df10c2161a9c2b814ac7844b31295ec4d7))

## v0.1.0 (2025-08-29)

### Feature

* Add web search server task with browser and verbose options ([`73d597a`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/73d597a279275abed80378c24ad2b1e6bb82ae59))
* Add web server task with --no-browser default behavior ([`b8e63c8`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/b8e63c85d01c4bcd0fee478c723b0e1b618a3f74))
* Add search task mirroring text_search cli api with fabric options ([`b9937dd`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/b9937dd8d7113d3dc75f9eeb877421883a982d6d))
* Add odoo plugin with hello world task ([`e66a325`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/e66a3253b5a3b704b54bdff73e80e7cc7c1ed2b3))
* Parallelize project/task/file/message searches using ThreadPoolExecutor ([`dcf9c87`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/dcf9c8742f5c33c102519c5b4dd7b5a0b26e62d9))
* Implement background process execution for concurrent web searches ([`41bf9ec`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/41bf9ec9813d4f538295e14e66d7450735ae7a3c))
* Convert modal interface to tabbed navigation for search, pins, and settings ([`bcb00ff`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/bcb00ffa1a092c3451498aead577f565726b58f3))
* Add pin functionality and scroll to results feature ([`080ac05`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/080ac0557fe0cad33f99597d41f6e17784769767))
* Update clear cache to also remove search history with confirmation ([`f888e6d`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/f888e6d3c9f838e8ab7df8433c39d7e02924f05f))
* Implement asynchronous search with concurrent XMLRPC calls for improved performance ([`3bc1bba`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/3bc1bbace6fc6f99c86596390a44fb46fb9a8ba6))
* Implement localStorage caching for search results with age display and refresh functionality ([`28c8434`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/28c84342eb958d2f50f5638db989f83490bff6cf))
* Change default port from 8080 to 1900 ([`18be7d4`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/18be7d427222b6306d8d58103d29e94e052a320f))
* Reload server environment when saving settings ([`e2a8d6d`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/e2a8d6d1b7aae4814c7678c5d897b32f339be717))
* Make search result counters clickable links to sections ([`2fe6e0e`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/2fe6e0e1415756ef2aa2da0c73dcc0c4c3bb3fca))
* Add message caching and JSON-safe output ([`7d9baf8`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7d9baf82af0021b6cb9e2dff7ef93f152d837dd8))
* Add web interface with caching and settings management ([`0c60fe0`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/0c60fe07cd1b2816bb5cb1b846615a130a3fb046))
* Enhance task search with stage/status information display ([`469c5ac`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/469c5ac8aacc51d95c4e65f448487bf49e3b88ea))
* Add text wrapping and vertical line formatting for descriptions ([`e4030ad`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/e4030adeeec6022207baddac8d5617e563b158d7))
* Improve message and task hierarchy display with better grouping and indentation ([`367c31f`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/367c31f3ed57f64b8c0d51acc809bd1d390f49e5))
* Remove dark text styling and add project link for tasks ([`9257702`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/92577028edd4ab4887a55af009beec5412da5216))
* Enhance text search result display with conditional verbose output and dark gray field names ([`962bc3d`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/962bc3da8bbe50b87e943f12fba381360cc21210))
* Improve user field handling in text search ([`9356058`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/93560588c816f2958c7240fb553d68e307ed3676))
* Create user debug tool for investigating user ID mapping and retrieval issues ([`7ca53b5`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7ca53b5d81c7fd170bce3f094a8dc5408d3226bc))
* Improve user ID extraction with verbose logging and error handling ([`6613e9f`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/6613e9f207d220111c6d4c81d731f17baf74ed5b))
* Add debug logging for user cache lookup in text search ([`bdbfe8d`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/bdbfe8d021dbdbe109b618a205a597a3d4b3e1aa))
* Improve user lookup with efficient caching mechanism ([`b21ba9b`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/b21ba9b50adee397a386e85a018d2b02ef8980ee))
* Improve user retrieval logic in text search tasks ([`7a65bb3`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7a65bb3cdf5736f4228c880c8f7afbc03849ca75))
* Make file search default and add option to exclude files ([`3307c21`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/3307c210d9e31f0ea2fec493459f2425d1840b60))
* Add file URL generation and terminal links for search results ([`1ca802d`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/1ca802d59a463c49bfd4826dbb0f5258267c3204))
* Improve error handling for partial objects in file search ([`07d50d7`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/07d50d7c8696c19007c5cf64ab05dc408a7a4f7a))
* Modify text_search.py to support optional search term with --download ([`93463ef`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/93463ef5d8d945985903d06013373f8eb191d0bf))
* Enhance text_search.py with unified file search and download capabilities ([`17defdb`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/17defdb92d406f9cd6e47b30d9f7fd96d854e534))
* Add Dutch language support for time references in text search ([`d4a9329`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/d4a93290346ecc06deeabce38be4e96195d55b4a))
* Modify text search to include logs by default with option to exclude ([`391cefd`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/391cefdb4a9504c608cc182a19ee8422cc0f2988))
* Add terminal hyperlinks for projects, tasks, and messages ([`3b6d23f`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/3b6d23f907339634d53020b37bc2629e3e33926b))
* Add HTML to markdown conversion for improved text readability ([`9bf80b8`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/9bf80b8d7ab90cd1d8989a01bdef80297cb68277))
* Add comprehensive text search module for Odoo projects and tasks ([`529c6e6`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/529c6e6f0b19d22ca2a4f5afa84ffdb574abff2f))

### Fix

* Resolve module import issues in web search server ([`895a576`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/895a576dab60028b69253f1315e19fa16d640d54))
* Validate search type parameter and handle unknown types with error ([`36d7d56`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/36d7d56bb6922ccbcfc0b850c95880339e4a2b54))
* Ensure all search categories execute and return results properly ([`3743836`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/374383691075f6ae8da07d4f82fc197f45576294))
* Enable debugging for search result collection and error handling ([`d6f8fa1`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/d6f8fa188010d9c07aa07a3078f07681062636d6))
* Ensure all search categories complete before returning results ([`a268469`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/a26846961f843471f4b87e7d86ccb995fb83d5b6))
* Escape f-string braces in subprocess code to prevent undefined name errors ([`7010e8c`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7010e8c4154decb98c2e14a3373c2d49ad2ccff0))
* Correct string escaping in download URL generation ([`6354721`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/6354721d74f3128e83d2ab0ed2f33ee3f054f8a0))
* Improve error handling and logging for web search subprocess execution ([`7c99a56`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7c99a56f154c23e811b7daddffd1fba6695f4041))
* Use sys.executable to ensure correct Python interpreter is used for subprocess ([`dac3435`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/dac3435f3c034dcf636c45454231b42067a94fe8))
* Scroll to search results now switches tabs and handles empty results ([`f30f5f1`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/f30f5f192fd8815110323f71a86509adbdba1321))
* Clear both cache and search history when clear cache button is clicked ([`2b06a35`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/2b06a35b3decf4f3b47f5719f353024859c7d52d))
* Remove async implementation to fix connection errors ([`bc0f753`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/bc0f753a5262fcf7c2ace36b54cf67ab09ec0a63))
* Update search resubmission logic to use button click instead of manual event dispatch ([`fad0214`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/fad0214826d6fcf8ad337b08cad96d7095abe89d))
* Refresh button now clears only specific query cache and resubmits search ([`e813d3c`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/e813d3cf0c1f73686163ed471f736529ee4ab307))
* Refresh button not working due to incorrect event handling ([`7a45e54`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7a45e548bf114958c37e69f21a938a8322a05637))
* Replace undefined make_json_safe method with inline data conversion logic ([`d144616`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/d144616899cd8ef313f8a2866c08ac2e30cbf9a6))
* Optimize message enrichment by batching task lookups instead of individual queries ([`bd35616`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/bd35616192f68aa14933753977945dca66c76e06))
* Use cached messages for search instead of database queries ([`eef0a7e`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/eef0a7e97688a93b2fee1fc6c995eea9b5098f10))
* Persist searcher instance to prevent cache rebuild and fix task_cache error ([`f5831e2`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/f5831e20a3404850dbd878f2f4c5375001ea2607))
* Correct regex replacement pattern for newlines in web search results ([`547e254`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/547e254b74ed9d34a340280844e077237c5ac830))
* Resolve invalid escape sequence warnings in web search server ([`db8f84a`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/db8f84a2d2f1a52dbbf3fe1a9f40de104e8cbd23))
* Improve settings display, message caching, and HTML to markdown conversion ([`522c5f1`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/522c5f188ed981a86ed776c609f3855a3eda3847))
* Enable verbose mode in web server to show search progress ([`7071cf2`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/7071cf2c3414fa052c25eb3ce443d2a10bc4a76d))
* Add missing JSON serialization method and remove duplicate code ([`4eeb00e`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/4eeb00eee513bac304b6727030e07a7d898afeaa))
* Convert Odoo Record objects to JSON-safe format in search results ([`613e7a9`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/613e7a9d313672f7c5d5abe606e67861564ef0a0))
* Remove duplicate console logging in web search server ([`1c00bc3`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/1c00bc388297ffd2879f494e3b20b0793690cf62))
* Remove duplicate console log in web search request handling ([`0f49a9f`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/0f49a9f080eff2da3719d5b280cd1fc616062c29))
* Remove duplicate console log in web search handler ([`2525048`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/252504802bb503cd717780d5d426405bae84dd19))
* Remove duplicate console log in web search handler ([`2d5f3bf`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/2d5f3bf179167b5b8f72fa12ac88b85be9d185b8))
* Improve error handling and console output in web search server and text search modules ([`62561eb`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/62561eb1b29a67e790d1c087e067273123f9436a))
* Create new OdooTextSearch instance per request and pass to url methods ([`03deed0`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/03deed03157cf2cb9cbdb255fe2e0c21f69debc3))
* Update project and task URL generation to use Odoo web interface format ([`d1db0f1`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/d1db0f151c3571ef35c66b342eeaca907ee31f51))
* Improve message placement logic for tasks in search results ([`fecdae7`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/fecdae704493d242c87f2163029f5c277f7e6d44))
* Remove unsupported `fields` parameter from Odoo search methods ([`d1945a1`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/d1945a1221503d465c68b238da1b61913f4c674b))
* Handle functools.partial user objects in text search ([`77ed490`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/77ed490a26e10c7c66782de821913e65f079c1f1))
* Handle partial attachment data and improve file download robustness ([`f414db6`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/f414db6378a3b2f2b38c385c7f9ff97c5f59f3a3))
* +.gitignore ([`3906938`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/39069385e28cec551aef09ea4b12513bb00ef2fe))
* Handle functools.partial tasks and add search output separator ([`ad9270c`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/ad9270c52af535f80532d39e42b03529b2742d7d))

### Documentation

* Replace playground content with edwh odoo plugin documentation and installation guide ([`399ad38`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/399ad388c2df1d61c7ac36ceb5b5a52ce25c6109))
* Update README.md with consistent `--no-` prefix option ([`c875d55`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/c875d5592ac95e628053bda94a77c554068ffd50))
* Fix README examples to use correct log filtering option ([`47c363e`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/47c363e5ac2eb4373d86c444080dffca49ec37e9))
* Update README with text_search.py details and usage ([`22cb193`](https://github.com/educationwarehouse/odoo_xmlrpc_playground/commit/22cb193f958137bb440ba11ae8f858892dd392b8))
